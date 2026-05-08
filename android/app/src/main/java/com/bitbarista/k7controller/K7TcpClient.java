package com.bitbarista.k7controller;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;

import javax.net.SocketFactory;

final class K7TcpClient {
    private static final String TAG = "K7TcpClient";
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

    private final Context context;
    private final String host;
    private final int port;
    private final int timeoutMs;

    K7TcpClient(Context context, String host, int port, int timeoutMs) {
        this.context = context.getApplicationContext();
        this.host = host == null || host.trim().isEmpty() ? DEFAULT_HOST : host.trim();
        this.port = port <= 0 ? DEFAULT_PORT : port;
        this.timeoutMs = timeoutMs <= 0 ? 1000 : timeoutMs;
    }

    void close() {
        // Stateless transport. Nothing to close.
    }

    JSONObject readAll() throws Exception {
        try (Connection conn = openConnection()) {
            sendPacket(conn, CMD_ALL_READ, new byte[0]);
            byte[] data = recv(conn.socket, conn.input, 256, 5000, true);
            return decodeState(data);
        }
    }

    void warmup() throws Exception {
        // No-op. The official app does not pre-read the socket.
    }

    void preview(int[] channels) throws Exception {
        // Fire-and-forget: preview is transient and the lamp reverts automatically.
        sendWithReconnect(CMD_PREVIEW, channelsToBytes(channels));
    }

    void hand(int[] channels) throws Exception {
        sendWithAck(CMD_HAND, channelsToBytes(channels));
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
        sendWithAck(CMD_ALL_SET, data.toByteArray());
    }

    // Send a command and wait briefly for the lamp's ACK before closing.
    // Mirrors ESP firmware's _recvAck() (150 ms window) so the lamp isn't
    // interrupted mid-processing by an abrupt socket close.
    private synchronized void sendWithAck(byte[] cmd, byte[] data) throws Exception {
        Exception first = null;
        for (int attempt = 1; attempt <= 2; attempt++) {
            try (Connection conn = openConnection()) {
                sendPacket(conn, cmd, data);
                try { recv(conn.socket, conn.input, 32, 150, false); } catch (Exception ignored) {}
                return;
            } catch (Exception e) {
                first = e;
                if (attempt < 2) Thread.sleep(250);
            }
        }
        throw first;
    }

    private synchronized void sendWithReconnect(byte[] cmd, byte[] data) throws Exception {
        Exception first = null;
        for (int attempt = 1; attempt <= 2; attempt++) {
            try (Connection conn = openConnection()) {
                sendPacket(conn, cmd, data);
                return;
            } catch (Exception e) {
                first = e;
                if (attempt < 2) Thread.sleep(250);
            }
        }
        throw first;
    }

    private void sendPacket(Connection conn, byte[] cmd, byte[] data) throws Exception {
        byte[] packet = packetBytes(cmd, data);
        Log.i(TAG, "send " + hex(packet));
        conn.output.write(packet);
        conn.output.flush();
    }

    private static byte[] packetBytes(byte[] cmd, byte[] data) {
        byte[] out = new byte[PKT_START.length + cmd.length + data.length + 1];
        int pos = 0;
        System.arraycopy(PKT_START, 0, out, pos, PKT_START.length);
        pos += PKT_START.length;
        System.arraycopy(cmd, 0, out, pos, cmd.length);
        pos += cmd.length;
        System.arraycopy(data, 0, out, pos, data.length);
        out[out.length - 1] = PKT_END;
        return out;
    }

    private static String hex(byte[] data) {
        StringBuilder out = new StringBuilder(data.length * 2);
        for (byte b : data) out.append(String.format("%02x", b & 0xff));
        return out.toString();
    }

    private Connection openConnection() throws Exception {
        Exception last = null;
        for (int attempt = 1; attempt <= 3; attempt++) {
            Socket socket = SocketFactory.getDefault().createSocket();
            try {
                Log.i(TAG, "connecting to " + host + ":" + port + " attempt " + attempt);
                socket.connect(new InetSocketAddress(host, port), timeoutMs);
                socket.setTcpNoDelay(true);
                socket.setSoTimeout(0);
                InputStream input = socket.getInputStream();
                OutputStream output = socket.getOutputStream();
                return new Connection(socket, input, output);
            } catch (Exception e) {
                last = e;
                try {
                    socket.close();
                } catch (Exception ignored) {}
                if (attempt < 3) Thread.sleep(250);
            }
        }
        throw last;
    }

    private static JSONObject decodeState(byte[] data) throws Exception {
        int start = findHeader(data, CMD_ALL_READ);
        if (start < 0) start = findHeader(data, null);
        if (start > 0) {
            byte[] trimmed = new byte[data.length - start];
            System.arraycopy(data, start, trimmed, 0, trimmed.length);
            data = trimmed;
        }
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

    private static int findHeader(byte[] data, byte[] cmd) {
        for (int i = 0; i + 3 < data.length; i++) {
            if (data[i] != RESP_MAGIC[0] || data[i + 1] != RESP_MAGIC[1]) continue;
            if (cmd == null || (data[i + 2] == cmd[0] && data[i + 3] == cmd[1])) return i;
        }
        return -1;
    }

    private static byte[] channelsToBytes(int[] values) {
        byte[] out = new byte[CHANNELS];
        if (values != null) {
            for (int i = 0; i < Math.min(CHANNELS, values.length); i++) out[i] = (byte) clamp(values[i]);
        }
        return out;
    }

    private static byte[] recv(Socket socket, InputStream input, int maxLen, int timeoutMs, boolean drain) throws IOException {
        int readTimeout = Math.max(1, timeoutMs);
        socket.setSoTimeout(readTimeout);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[Math.max(1, maxLen)];
        while (out.size() < maxLen) {
            int n;
            try {
                n = input.read(buf, 0, Math.min(buf.length, maxLen - out.size()));
            } catch (SocketTimeoutException e) {
                break;
            }
            if (n < 0) break;
            if (n == 0) continue;
            out.write(buf, 0, n);
            if (!drain) break;
        }
        socket.setSoTimeout(0);
        return out.toByteArray();
    }

    private static final class Connection implements Closeable {
        final Socket socket;
        final InputStream input;
        final OutputStream output;

        Connection(Socket socket, InputStream input, OutputStream output) {
            this.socket = socket;
            this.input = input;
            this.output = output;
        }

        @Override
        public void close() {
            // Close the socket only; in Java, closing the InputStream first is
            // equivalent to socket.close() and triggers RST if there's unread
            // data. Closing the socket directly sends a clean FIN instead.
            try { socket.close(); } catch (Exception ignored) {}
        }
    }

    static int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }
}
