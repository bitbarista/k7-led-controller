package com.bitbarista.k7controller;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

final class LocalBridgeServer implements Runnable {
    private static final String TAG = "K7LocalBridge";
    private static final int PORT = 8787;

    private final Context context;
    private final SharedPreferences prefs;
    private final Object lampLock = new Object();
    private K7TcpClient lampClient;
    private String lampClientHost = "";
    private int lampClientPort = -1;
    private volatile boolean running;
    private ServerSocket serverSocket;
    private Thread thread;

    LocalBridgeServer(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = this.context.getSharedPreferences("k7_android_bridge", Context.MODE_PRIVATE);
    }

    void start() {
        if (thread != null) return;
        running = true;
        thread = new Thread(this, "k7-local-bridge");
        thread.start();
    }

    void stop() {
        running = false;
        try {
            if (serverSocket != null) serverSocket.close();
        } catch (Exception ignored) {}
    }

    @Override
    public void run() {
        try {
            serverSocket = new ServerSocket(PORT);
            while (running) {
                Socket socket = serverSocket.accept();
                new Thread(() -> handle(socket), "k7-local-request").start();
            }
        } catch (Exception e) {
            if (running) Log.e(TAG, "server stopped", e);
        }
    }

    private void handle(Socket socket) {
        try {
            InputStream in = socket.getInputStream();
            byte[] headerBytes = readHeader(in);
            if (headerBytes.length == 0) return;
            String header = new String(headerBytes, StandardCharsets.UTF_8);
            String[] lines = header.split("\\r?\\n");
            String[] request = lines[0].split(" ");
            String method = request[0];
            String path = request.length > 1 ? request[1] : "/";
            int contentLength = 0;
            for (String line : lines) {
                int idx = line.indexOf(':');
                if (idx > 0 && line.substring(0, idx).trim().equalsIgnoreCase("content-length")) {
                    contentLength = Integer.parseInt(line.substring(idx + 1).trim());
                }
            }
            byte[] body = readBody(in, contentLength);
            Response response = route(method, path, body);
            writeResponse(socket.getOutputStream(), response);
        } catch (Exception e) {
            Log.e(TAG, "request failed", e);
            try {
                writeResponse(socket.getOutputStream(), error(502, e.getMessage() == null ? "Lamp request failed" : e.getMessage()));
            } catch (Exception ignored) {}
        } finally {
            try {
                socket.close();
            } catch (Exception ignored) {}
        }
    }

    private Response route(String method, String rawPath, byte[] body) throws Exception {
        String path = rawPath.split("\\?", 2)[0];
        if (path.equals("/")) return redirect("/static/mobile.html");
        if (path.startsWith("/static/")) return asset(path.substring(1));
        if (path.equals("/api/version")) return json(new JSONObject().put("bridge", "android").put("platform", "android").put("transport", "direct_lamp"));
        if (path.equals("/api/capabilities")) return json(capabilities());
        if (path.equals("/api/config")) return config(method, body);
        if (path.equals("/api/devices")) return json(devices());
        if (path.equals("/api/master")) return master(method, body);
        if (path.equals("/api/state")) return json(state());
        if (path.equals("/api/lamp/read")) return lampRead();
        if (path.equals("/api/presets")) return presets();
        if (path.equals("/api/profiles")) return json(new JSONObject());
        if (path.startsWith("/api/profiles/")) return json(new JSONObject().put("ok", true));
        if (path.equals("/api/preview")) return lampChannels(body, false);
        if (path.equals("/api/hand")) return lampChannels(body, true);
        if (path.equals("/api/push")) return push(body);
        if (path.equals("/api/siesta/status")) return json(getObject("siesta", defaultSiesta()));
        if (path.equals("/api/siesta/schedule")) return saveObject("siesta", new JSONObject(new String(body, StandardCharsets.UTF_8)), true);
        if (path.equals("/api/lunar/status")) return json(getObject("lunar", defaultLunar()));
        if (path.equals("/api/lunar/schedule")) return saveObject("lunar", normalizeLunar(new JSONObject(new String(body, StandardCharsets.UTF_8))), true);
        if (path.equals("/api/lunar/start")) return setLunar(true);
        if (path.equals("/api/lunar/stop")) return setLunar(false);
        if (path.equals("/api/backup")) return json(new JSONObject().put("kind", "k7_android_backup").put("state", state()));
        if (path.equals("/api/community-presets")) return communityPresets();
        return error(404, "Not found");
    }

    private JSONObject capabilities() throws Exception {
        JSONObject caps = new JSONObject();
        caps.put("read_lamp", true).put("push_schedule", true).put("manual_preview", true);
        caps.put("profiles", true).put("community_presets", true).put("community_presets_browse", true).put("backup_restore", true);
        caps.put("fixed_lunar", true).put("siesta_baked_schedule", true);
        caps.put("smooth_ramp", false).put("tracked_lunar", false).put("acclimation", false);
        caps.put("seasonal_daylength", false).put("feed_mode", false).put("maintenance_mode", false);
        caps.put("setup_portal", false).put("logs", false).put("persistent_controller_clock", false);
        return new JSONObject().put("platform", "android").put("transport", "direct_lamp").put("capabilities", caps);
    }

    private Response config(String method, byte[] body) throws Exception {
        if ("POST".equals(method)) {
            JSONObject in = new JSONObject(new String(body, StandardCharsets.UTF_8));
            prefs.edit()
                    .putString("host", in.optString("host", K7TcpClient.DEFAULT_HOST))
                    .putInt("port", in.optInt("port", K7TcpClient.DEFAULT_PORT))
                    .putString("device", in.optString("device", "k7mini"))
                    .apply();
            synchronized (lampLock) {
                if (lampClient != null) {
                    lampClient.close();
                    lampClient = null;
                }
            }
        }
        if ("GET".equals(method)) {
            warmLampSocket();
        }
        return json(new JSONObject()
                .put("host", prefs.getString("host", K7TcpClient.DEFAULT_HOST))
                .put("port", prefs.getInt("port", K7TcpClient.DEFAULT_PORT))
                .put("device", prefs.getString("device", "k7mini")));
    }

    private Response master(String method, byte[] body) throws Exception {
        if ("POST".equals(method)) {
            int value = new JSONObject(new String(body, StandardCharsets.UTF_8)).optInt("value", 100);
            prefs.edit().putInt("master", Math.max(0, Math.min(200, value))).apply();
        }
        return json(new JSONObject().put("value", prefs.getInt("master", 100)));
    }

    private Response lampRead() throws Exception {
        JSONObject lamp;
        synchronized (lampLock) {
            lamp = client().readAll();
        }
        saveStateFromLamp(lamp);
        return json(lamp);
    }

    private Response lampChannels(byte[] body, boolean hand) throws Exception {
        int[] channels = intArray(new JSONObject(new String(body, StandardCharsets.UTF_8)).getJSONArray("channels"), K7TcpClient.CHANNELS);
        synchronized (lampLock) {
            if (hand) client().hand(channels);
            else client().preview(channels);
        }
        if (hand) saveState(state().put("mode", "manual").put("manual", jsonArray(channels)));
        return json(new JSONObject().put("ok", true));
    }

    private Response push(byte[] body) throws Exception {
        JSONObject in = new JSONObject(new String(body, StandardCharsets.UTF_8));
        int[] manual = intArray(in.getJSONArray("manual"), K7TcpClient.CHANNELS);
        int[][] schedule = scheduleArray(in.getJSONArray("schedule"));
        String activePreset = in.optString("active_preset", "");
        JSONObject lunar = getObject("lunar", defaultLunar());
        if ("preset:dino".equalsIgnoreCase(activePreset.trim())) {
            lunar.put("enabled", false).put("active", false);
            putObject("lunar", lunar);
        }
        JSONObject siesta = getObject("siesta", defaultSiesta());
        int[][] baseSchedule = copy(schedule);
        schedule = bakeEffects(baseSchedule, siesta, lunar);
        int master = prefs.getInt("master", 100);
        manual = scale(manual, master);
        schedule = scale(schedule, master);
        boolean autoMode = !"manual".equals(in.optString("mode", "auto"));
        synchronized (lampLock) {
            client().push(manual, schedule, autoMode);
        }
        putObject("base_schedule", new JSONObject().put("schedule", scheduleJson(baseSchedule)));
        saveState(state().put("mode", autoMode ? "auto" : "manual").put("manual", jsonArray(manual)).put("schedule", scheduleJson(baseSchedule)).put("active_preset", activePreset));
        return json(new JSONObject().put("ok", true).put("verified", false));
    }

    private static final String COMMUNITY_PRESETS_URL = "https://bitbarista.github.io/k7-led-controller/community-presets/index.json";

    private Response communityPresets() throws Exception {
        java.net.HttpURLConnection conn = (java.net.HttpURLConnection) new java.net.URL(COMMUNITY_PRESETS_URL).openConnection();
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(10000);
        conn.setRequestProperty("Accept", "application/json");
        try {
            int status = conn.getResponseCode();
            if (status != 200) throw new Exception("Community presets fetch failed: HTTP " + status);
            try (InputStream in = conn.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                return new Response(200, "application/json", out.toByteArray());
            }
        } finally {
            conn.disconnect();
        }
    }

    private Response presets() throws Exception {
        JSONObject all = new JSONObject(readAssetText("presets.json"));
        String device = prefs.getString("device", "k7mini");
        return json(all.optJSONObject(device) != null ? all.getJSONObject(device) : all.getJSONObject("k7mini"));
    }

    private JSONObject state() throws Exception {
        String raw = prefs.getString("state", null);
        if (raw != null) return new JSONObject(raw);
        return new JSONObject().put("name", "").put("mode", "auto").put("manual", new JSONArray("[0,0,0,0,0,0]")).put("schedule", defaultSchedule()).put("schedule_shift_minutes", 0).put("master_brightness", 100);
    }

    private void saveState(JSONObject state) {
        prefs.edit().putString("state", state.toString()).apply();
    }

    private void saveStateFromLamp(JSONObject lamp) throws Exception {
        JSONObject s = state();
        if (!"manual".equals(s.optString("mode"))) s.put("mode", lamp.optBoolean("auto_mode") ? "auto" : "auto");
        s.put("name", lamp.optString("name", ""));
        s.put("manual", lamp.getJSONArray("manual"));
        s.put("schedule", lamp.getJSONArray("schedule"));
        s.put("last_read_at", Long.toString(System.currentTimeMillis()));
        saveState(s);
    }

    private K7TcpClient client() {
        String host = prefs.getString("host", K7TcpClient.DEFAULT_HOST);
        int port = prefs.getInt("port", K7TcpClient.DEFAULT_PORT);
        if (lampClient == null || !host.equals(lampClientHost) || port != lampClientPort) {
            if (lampClient != null) lampClient.close();
            lampClient = new K7TcpClient(context, host, port, 2000);
            lampClientHost = host;
            lampClientPort = port;
        }
        return lampClient;
    }

    private void warmLampSocket() {
        new Thread(() -> {
            synchronized (lampLock) {
                try {
                    client().warmup();
                } catch (Exception e) {
                    Log.w(TAG, "lamp socket warmup failed", e);
                }
            }
        }, "k7-lamp-warmup").start();
    }

    private static int[][] bakeEffects(int[][] schedule, JSONObject siesta, JSONObject lunar) {
        int[][] out = copy(schedule);
        if (siesta.optBoolean("enabled")) {
            int start = parseHHMM(siesta.optString("start", "13:00"), 13 * 60);
            int end = start + siesta.optInt("duration", siesta.optInt("duration_mins", 90));
            int factor = 100 - Math.max(1, Math.min(90, siesta.optInt("intensity", 25)));
            for (int[] row : out) {
                int mins = row[0] * 60 + row[1];
                if (mins >= start && mins < end) for (int c = 2; c < 8; c++) row[c] = row[c] * factor / 100;
            }
        }
        if (lunar.optBoolean("enabled")) {
            int start = parseHHMM(lunar.optString("start", "18:30"), 18 * 60 + 30);
            int end = parseHHMM(lunar.optString("end", "06:30"), 6 * 60 + 30);
            int max = Math.max(0, Math.min(100, lunar.optInt("max_intensity", 15)));
            int threshold = Math.max(0, Math.min(100, lunar.optInt("day_threshold", 2)));
            for (int[] row : out) {
                int mins = row[0] * 60 + row[1];
                if (minsInWindow(mins, start, end) && maxChannel(row) <= threshold) {
                    row[3] = Math.max(row[3], max);
                    row[6] = Math.max(row[6], (max * 7 + 5) / 10);
                }
            }
        }
        return out;
    }

    private Response setLunar(boolean enabled) throws Exception {
        JSONObject lunar = getObject("lunar", defaultLunar()).put("enabled", enabled).put("active", enabled);
        putObject("lunar", lunar);
        return json(new JSONObject().put("ok", true));
    }

    private Response saveObject(String key, JSONObject value, boolean normalize) throws Exception {
        if ("lunar".equals(key) && normalize) value = normalizeLunar(value);
        if ("siesta".equals(key)) value.put("active", value.optBoolean("enabled")).put("duration_mins", value.optInt("duration", 90));
        putObject(key, value);
        return json(value);
    }

    private JSONObject getObject(String key, JSONObject fallback) throws Exception {
        String raw = prefs.getString(key, null);
        return raw == null ? fallback : new JSONObject(raw);
    }

    private void putObject(String key, JSONObject value) {
        prefs.edit().putString(key, value.toString()).apply();
    }

    private static JSONObject defaultSiesta() throws Exception {
        return new JSONObject().put("enabled", false).put("active", false).put("start", "13:00").put("duration", 90).put("duration_mins", 90).put("intensity", 25);
    }

    private static JSONObject defaultLunar() throws Exception {
        return new JSONObject().put("enabled", false).put("active", false).put("phase", 4).put("illumination", 100).put("phase_name", "Fixed").put("start", "18:30").put("end", "06:30").put("clamp_start", "18:00").put("clamp_end", "08:00").put("max_intensity", 15).put("day_threshold", 2).put("track_moonrise", false);
    }

    private static JSONObject normalizeLunar(JSONObject in) throws Exception {
        JSONObject out = defaultLunar();
        java.util.Iterator<String> keys = in.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            out.put(key, in.get(key));
        }
        out.put("track_moonrise", false).put("active", out.optBoolean("enabled")).put("phase", 4).put("illumination", 100).put("phase_name", "Fixed");
        return out;
    }

    private Response asset(String path) throws Exception {
        String assetPath = URLDecoder.decode(path, "UTF-8");
        byte[] data = readAssetBytes(assetPath);
        return new Response(200, contentType(assetPath), data);
    }

    private String readAssetText(String path) throws Exception {
        return new String(readAssetBytes(path), StandardCharsets.UTF_8);
    }

    private byte[] readAssetBytes(String path) throws Exception {
        AssetManager assets = context.getAssets();
        try (InputStream in = assets.open(path); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }

    private static Response json(JSONObject obj) {
        return new Response(200, "application/json", obj.toString().getBytes(StandardCharsets.UTF_8));
    }

    private static Response error(int status, String message) throws Exception {
        return new Response(status, "application/json", new JSONObject().put("error", message).toString().getBytes(StandardCharsets.UTF_8));
    }

    private static Response redirect(String location) {
        return new Response(302, "text/plain", new byte[0], "Location: " + location + "\r\n");
    }

    private static void writeResponse(OutputStream out, Response r) throws Exception {
        out.write(("HTTP/1.1 " + r.status + " OK\r\nContent-Type: " + r.type + "\r\nAccess-Control-Allow-Origin: *\r\n" + r.extraHeaders + "Content-Length: " + r.body.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(r.body);
        out.flush();
    }

    private static byte[] readHeader(InputStream in) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int b, matched = 0;
        byte[] end = {'\r', '\n', '\r', '\n'};
        while ((b = in.read()) >= 0) {
            out.write(b);
            matched = b == end[matched] ? matched + 1 : 0;
            if (matched == end.length) break;
        }
        return out.toByteArray();
    }

    private static byte[] readBody(InputStream in, int len) throws Exception {
        byte[] out = new byte[len];
        int pos = 0;
        while (pos < len) {
            int n = in.read(out, pos, len - pos);
            if (n <= 0) break;
            pos += n;
        }
        return out;
    }

    private static JSONObject devices() throws Exception {
        return new JSONObject().put("k7mini", new JSONObject().put("label", "K7 Mini").put("channels", new JSONArray("[\"white\",\"royal_blue\",\"blue\"]"))).put("k7pro", new JSONObject().put("label", "K7 Pro").put("channels", new JSONArray("[\"white\",\"royal_blue\",\"green\",\"uv\",\"cyan\",\"red\"]")));
    }

    private static JSONArray defaultSchedule() throws Exception {
        JSONArray rows = new JSONArray();
        for (int h = 0; h < K7TcpClient.SLOTS; h++) rows.put(new JSONArray().put(h).put(0).put(0).put(0).put(0).put(0).put(0).put(0));
        return rows;
    }

    private static int[] intArray(JSONArray arr, int len) {
        int[] out = new int[len];
        for (int i = 0; i < Math.min(len, arr.length()); i++) out[i] = K7TcpClient.clamp(arr.optInt(i));
        return out;
    }

    private static int[][] scheduleArray(JSONArray arr) {
        int[][] out = new int[K7TcpClient.SLOTS][8];
        for (int h = 0; h < K7TcpClient.SLOTS; h++) {
            JSONArray row = arr.optJSONArray(h);
            for (int c = 0; c < 8; c++) out[h][c] = K7TcpClient.clamp(row == null ? 0 : row.optInt(c));
        }
        return out;
    }

    private static JSONArray jsonArray(int[] values) {
        JSONArray out = new JSONArray();
        for (int value : values) out.put(value);
        return out;
    }

    private static JSONArray scheduleJson(int[][] schedule) {
        JSONArray out = new JSONArray();
        for (int[] src : schedule) out.put(jsonArray(src));
        return out;
    }

    private static int[] scale(int[] values, int master) {
        int[] out = new int[values.length];
        for (int i = 0; i < values.length; i++) out[i] = values[i] * master / 100;
        return out;
    }

    private static int[][] scale(int[][] values, int master) {
        int[][] out = copy(values);
        for (int h = 0; h < out.length; h++) for (int c = 2; c < 8; c++) out[h][c] = out[h][c] * master / 100;
        return out;
    }

    private static int[][] copy(int[][] values) {
        int[][] out = new int[values.length][8];
        for (int i = 0; i < values.length; i++) System.arraycopy(values[i], 0, out[i], 0, 8);
        return out;
    }

    private static int parseHHMM(String value, int fallback) {
        try {
            String[] parts = value.split(":");
            return Integer.parseInt(parts[0]) * 60 + Integer.parseInt(parts[1]);
        } catch (Exception ignored) {
            return fallback;
        }
    }

    private static boolean minsInWindow(int mins, int start, int end) {
        return start < end ? mins >= start && mins < end : mins >= start || mins < end;
    }

    private static int maxChannel(int[] row) {
        int max = 0;
        for (int i = 2; i < 8; i++) max = Math.max(max, row[i]);
        return max;
    }

    private static String contentType(String path) {
        String p = path.toLowerCase(Locale.ROOT);
        if (p.endsWith(".html")) return "text/html; charset=utf-8";
        if (p.endsWith(".js")) return "application/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".json")) return "application/json";
        return "application/octet-stream";
    }

    private static final class Response {
        final int status;
        final String type;
        final byte[] body;
        final String extraHeaders;

        Response(int status, String type, byte[] body) {
            this(status, type, body, "");
        }

        Response(int status, String type, byte[] body, String extraHeaders) {
            this.status = status;
            this.type = type;
            this.body = body;
            this.extraHeaders = extraHeaders;
        }
    }
}
