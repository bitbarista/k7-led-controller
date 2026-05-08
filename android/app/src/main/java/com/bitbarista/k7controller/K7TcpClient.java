package com.bitbarista.k7controller;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
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
    private Socket socket;
    private InputStream input;
    private OutputStream output;
    private Thread readerThread;
    private final Object stateLock = new Object();
    private JSONObject lastState;
    private int stateGeneration;

    K7TcpClient(Context context, String host, int port, int timeoutMs) {
        this.context = context.getApplicationContext();
        this.host = host == null || host.trim().isEmpty() ? DEFAULT_HOST : host.trim();
        this.port = port <= 0 ? DEFAULT_PORT : port;
        this.timeoutMs = timeoutMs <= 0 ? 1000 : timeoutMs;
    }

    void close() {
        closeQuietly();
    }

    JSONObject readAll() throws Exception {
        int expectedGeneration;
        synchronized (stateLock) {
            expectedGeneration = stateGeneration;
        }
        sendWithReconnect(CMD_ALL_READ, new byte[0]);
        long deadline = System.currentTimeMillis() + 5000;
        synchronized (stateLock) {
            while (stateGeneration <= expectedGeneration) {
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0) break;
                stateLock.wait(Math.min(remaining, 500));
            }
            if (stateGeneration > expectedGeneration && lastState != null) {
                return new JSONObject(lastState.toString());
            }
        }
        throw new IllegalStateException("No read-all response");
    }

    void warmup() throws Exception {
        connect();
    }

    void preview(int[] channels) throws Exception {
        sendWithReconnect(CMD_PREVIEW, channelsToBytes(channels));
    }

    void hand(int[] channels) throws Exception {
        sendWithReconnect(CMD_HAND, channelsToBytes(channels));
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
        sendWithReconnect(CMD_ALL_SET, data.toByteArray());
    }

    private synchronized void sendWithReconnect(byte[] cmd, byte[] data) throws Exception {
        try {
            sendPacket(cmd, data);
        } catch (Exception first) {
            closeQuietly();
            sendPacket(cmd, data);
        }
    }

    private synchronized void sendPacket(byte[] cmd, byte[] data) throws Exception {
        connect();
        Log.i(TAG, "send " + hex(packetBytes(cmd, data)));
        output.write(PKT_START);
        output.write(cmd);
        output.write(data);
        output.write(PKT_END);
        output.flush();
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

    private synchronized void connect() throws Exception {
        if (socket != null && socket.isConnected() && !socket.isClosed()) return;
        Network wifi = wifiNetwork();
        Exception last = null;
        for (int attempt = 1; attempt <= 3; attempt++) {
            Socket socket = wifi != null ? wifi.getSocketFactory().createSocket() : SocketFactory.getDefault().createSocket();
            try {
                if (wifi != null) Log.i(TAG, "connecting to " + host + ":" + port + " over WiFi network " + wifi + " attempt " + attempt);
                else Log.w(TAG, "no WiFi network available; using default network for " + host + ":" + port + " attempt " + attempt);
                socket.connect(new InetSocketAddress(host, port), timeoutMs);
                socket.setTcpNoDelay(true);
                socket.setSoTimeout(timeoutMs);
                this.socket = socket;
                this.input = socket.getInputStream();
                this.output = socket.getOutputStream();
                startReader(socket, this.input);
                return;
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

    private synchronized void startReader(Socket readerSocket, InputStream readerInput) {
        if (readerThread != null && readerThread.isAlive()) return;
        readerThread = new Thread(() -> readLoop(readerSocket, readerInput), "k7-lamp-reader");
        readerThread.setDaemon(true);
        readerThread.start();
    }

    private void readLoop(Socket readerSocket, InputStream readerInput) {
        ByteArrayOutputStream pending = new ByteArrayOutputStream();
        byte[] buf = new byte[256];
        try {
            while (true) {
                synchronized (this) {
                    if (readerSocket != socket || readerSocket.isClosed()) return;
                }
                int n = readerInput.read(buf);
                if (n < 0) return;
                if (n == 0) continue;
                pending.write(buf, 0, n);
                consumeResponses(pending);
            }
        } catch (Exception e) {
            synchronized (this) {
                if (readerSocket == socket) closeQuietly();
            }
        }
    }

    private void consumeResponses(ByteArrayOutputStream pending) {
        byte[] data = pending.toByteArray();
        int stateStart = findHeader(data, CMD_ALL_READ);
        if (stateStart >= 0 && data.length - stateStart >= 214) {
            int end = findPacketEnd(data, stateStart);
            if (end > stateStart) {
                int len = end - stateStart + 1;
                byte[] packet = new byte[len];
                System.arraycopy(data, stateStart, packet, 0, len);
                try {
                    JSONObject state = decodeState(packet);
                    synchronized (stateLock) {
                        lastState = state;
                        stateGeneration++;
                        stateLock.notifyAll();
                    }
                } catch (Exception ignored) {
                }
                pending.reset();
                if (end + 1 < data.length) {
                    pending.write(data, end + 1, data.length - end - 1);
                }
            }
        } else if (data.length > 512) {
            pending.reset();
        }
    }

    private static int findPacketEnd(byte[] data, int start) {
        for (int i = start + 4; i < data.length; i++) {
            if (data[i] == PKT_END) return i;
        }
        return -1;
    }

    private synchronized void closeQuietly() {
        Thread oldReader = readerThread;
        readerThread = null;
        try {
            if (input != null) input.close();
        } catch (Exception ignored) {}
        try {
            if (output != null) output.close();
        } catch (Exception ignored) {}
        try {
            if (socket != null) socket.close();
        } catch (Exception ignored) {}
        input = null;
        output = null;
        socket = null;
        if (oldReader != null && oldReader != Thread.currentThread()) oldReader.interrupt();
    }

    private Network wifiNetwork() {
        ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return null;
        Network active = cm.getActiveNetwork();
        Network activeWifi = null;
        for (Network network : cm.getAllNetworks()) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(network);
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                if (network.equals(active)) return network;
                activeWifi = network;
            }
        }
        return activeWifi;
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

    static int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }
}
