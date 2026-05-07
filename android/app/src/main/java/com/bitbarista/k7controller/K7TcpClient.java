package com.bitbarista.k7controller;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

final class K7TcpClient {
    static final int CHANNELS = 6;
    static final int SLOTS = 24;
    static final String DEFAULT_HOST = "192.168.4.1";
    static final int DEFAULT_PORT = 8266;

    private static final byte[] PKT_START = {(byte) 0xaa, (byte) 0xa5};
    private static final byte PKT_END = (byte) 0xbb;
    private static final byte[] RESP_MAGIC = {(byte) 0xab, (byte) 0xaa};
    private static final byte[] CMD_HAND = {0x10, 0x05};
    private static final byte[] CMD_PREVIEW = {0x10, 0x06};
    private static final byte[] CMD_ALL_SET = {0x10, 0x07};
    private static final byte[] CMD_ALL_READ = {0x10, 0x08};

    private final String host;
    private final int port;
    private final int timeoutMs;

    K7TcpClient(String host, int port, int timeoutMs) {
        this.host = host == null || host.trim().isEmpty() ? DEFAULT_HOST : host.trim();
        this.port = port <= 0 ? DEFAULT_PORT : port;
        this.timeoutMs = timeoutMs <= 0 ? 1000 : timeoutMs;
    }

    JSONObject readAll() throws Exception {
        try (Socket socket = connect()) {
            sendPacket(socket, CMD_ALL_READ, new byte[0]);
            tryRead(socket, 32, 100, false);
            return decodeState(tryRead(socket, 256, 5000, true));
        }
    }

    void preview(int[] channels) throws Exception {
        try (Socket socket = connect()) {
            sendPacket(socket, CMD_PREVIEW, channelsToBytes(channels));
        }
    }

    void hand(int[] channels) throws Exception {
        try (Socket socket = connect()) {
            sendPacket(socket, CMD_HAND, channelsToBytes(channels));
            tryRead(socket, 32, 150, false);
        }
    }

    void push(int[] manual, int[][] schedule, boolean autoMode) throws Exception {
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        data.write(channelsToBytes(manual));
        data.write(SLOTS);
        for (int h = 0; h < SLOTS; h++) {
            for (int c = 0; c < 8; c++) data.write(clamp(schedule[h][c]));
        }
        data.write(autoMode ? 1 : 0);
        java.util.Calendar now = java.util.Calendar.getInstance();
        data.write(now.get(java.util.Calendar.HOUR_OF_DAY));
        data.write(now.get(java.util.Calendar.MINUTE));
        data.write(now.get(java.util.Calendar.SECOND));
        try (Socket socket = connect()) {
            sendPacket(socket, CMD_ALL_SET, data.toByteArray());
            tryRead(socket, 32, 150, false);
        }
    }

    private Socket connect() throws Exception {
        Socket socket = new Socket();
        socket.connect(new InetSocketAddress(host, port), timeoutMs);
        socket.setSoTimeout(20);
        tryRead(socket, 64, 20, false);
        socket.setSoTimeout(timeoutMs);
        return socket;
    }

    private static void sendPacket(Socket socket, byte[] cmd, byte[] data) throws Exception {
        OutputStream out = socket.getOutputStream();
        out.write(PKT_START);
        out.write(cmd);
        out.write(data);
        out.write(PKT_END);
        out.flush();
    }

    private static byte[] tryRead(Socket socket, int maxLen, int timeoutMs, boolean drain) {
        try {
            socket.setSoTimeout(timeoutMs);
            InputStream in = socket.getInputStream();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[maxLen];
            while (out.size() < maxLen) {
                int n = in.read(buf, 0, Math.min(buf.length, maxLen - out.size()));
                if (n <= 0) break;
                out.write(buf, 0, n);
                if (!drain) break;
            }
            return out.toByteArray();
        } catch (Exception ignored) {
            return new byte[0];
        }
    }

    private static JSONObject decodeState(byte[] data) throws Exception {
        if (data.length < 10 || data[0] != RESP_MAGIC[0] || data[1] != RESP_MAGIC[1] || data[data.length - 1] != PKT_END) {
            throw new IllegalStateException("Bad read-all response");
        }
        int pos = 4;
        JSONArray manual = new JSONArray();
        for (int i = 0; i < CHANNELS; i++) manual.put(data[pos + i] & 0xff);
        pos += CHANNELS;
        int timeNum = data[pos++] & 0xff;
        JSONArray schedule = new JSONArray();
        for (int i = 0; i < timeNum && i < SLOTS; i++) {
            JSONArray row = new JSONArray();
            for (int j = 0; j < 8; j++) row.put(data[pos + j] & 0xff);
            schedule.put(row);
            pos += 8;
        }
        while (schedule.length() < SLOTS) {
            JSONArray row = new JSONArray();
            row.put(schedule.length()).put(0).put(0).put(0).put(0).put(0).put(0).put(0);
            schedule.put(row);
        }
        boolean autoMode = (data[pos++] & 0xff) != 0;
        int nameEnd = pos;
        while (nameEnd < data.length - 1 && nameEnd < pos + 11 && data[nameEnd] != 0) nameEnd++;
        JSONObject out = new JSONObject();
        out.put("name", new String(data, pos, nameEnd - pos, StandardCharsets.UTF_8));
        out.put("auto_mode", autoMode);
        out.put("manual", manual);
        out.put("schedule", schedule);
        out.put("valid", true);
        return out;
    }

    private static byte[] channelsToBytes(int[] values) {
        byte[] out = new byte[CHANNELS];
        if (values != null) {
            for (int i = 0; i < Math.min(CHANNELS, values.length); i++) out[i] = (byte) clamp(values[i]);
        }
        return out;
    }

    static int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }
}
