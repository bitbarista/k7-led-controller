package com.bitbarista.k7controller;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.util.Log;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

public class FeedWidget extends AppWidgetProvider {

    private static final String TAG = "K7FeedWidget";
    static final String ACTION_TOGGLE_FEED  = "com.bitbarista.k7controller.TOGGLE_FEED";
    static final String ACTION_TOGGLE_MAINT = "com.bitbarista.k7controller.TOGGLE_MAINT";

    @Override
    public void onUpdate(Context ctx, AppWidgetManager mgr, int[] ids) {
        for (int id : ids) {
            final int widgetId = id;
            new Thread(() -> refreshWidget(ctx, mgr, widgetId)).start();
        }
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        super.onReceive(ctx, intent);
        String action = intent.getAction();
        if (!ACTION_TOGGLE_FEED.equals(action) && !ACTION_TOGGLE_MAINT.equals(action)) return;

        boolean isFeed = ACTION_TOGGLE_FEED.equals(action);
        BroadcastReceiver.PendingResult result = goAsync();
        new Thread(() -> {
            try {
                toggle(ctx, isFeed);
                AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
                int[] ids = mgr.getAppWidgetIds(new ComponentName(ctx, FeedWidget.class));
                for (int id : ids) refreshWidget(ctx, mgr, id);
            } finally {
                result.finish();
            }
        }).start();
    }

    static void refreshWidget(Context ctx, AppWidgetManager mgr, int widgetId) {
        String host = getLampHost(ctx);
        String base = "http://" + host;
        boolean feedActive = false, maintActive = false;
        int feedRemaining = 0, maintRemaining = 0;
        boolean offline = false;
        try {
            JSONObject s = httpGet(ctx, base + "/api/feed/status");
            feedActive = s.optBoolean("active", false);
            feedRemaining = s.optInt("remaining", 0);
            JSONObject m = httpGet(ctx, base + "/api/maintenance/status");
            maintActive = m.optBoolean("active", false);
            maintRemaining = m.optInt("remaining", 0);
        } catch (Exception e) {
            Log.w(TAG, "lamp unreachable: " + e.getMessage());
            offline = true;
        }
        applyViews(ctx, mgr, widgetId, feedActive, feedRemaining, maintActive, maintRemaining, offline);
    }

    private static void applyViews(Context ctx, AppWidgetManager mgr, int widgetId,
            boolean feedActive, int feedRemaining,
            boolean maintActive, int maintRemaining,
            boolean offline) {
        RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget_feed);

        // Feed button
        String feedText = feedActive
                ? (feedRemaining > 0 ? "Feed\n" + formatSecs(feedRemaining) : "Feed ●")
                : "Feed";
        v.setTextViewText(R.id.btn_feed, feedText);
        v.setTextColor(R.id.btn_feed, feedActive ? 0xFFFFFFFF : 0xFFB0B8C4);
        v.setInt(R.id.btn_feed, "setBackgroundResource",
                feedActive ? R.drawable.widget_btn_feed_active : R.drawable.widget_btn);

        // Maintenance button
        String maintText = maintActive
                ? (maintRemaining > 0 ? "Maint\n" + formatSecs(maintRemaining) : "Maint ●")
                : "Maintenance";
        v.setTextViewText(R.id.btn_maint, maintText);
        v.setTextColor(R.id.btn_maint, maintActive ? 0xFFFFFFFF : 0xFFB0B8C4);
        v.setInt(R.id.btn_maint, "setBackgroundResource",
                maintActive ? R.drawable.widget_btn_maint_active : R.drawable.widget_btn);

        // Status line
        v.setTextViewText(R.id.widget_status, offline ? "Offline" : "");

        // Tap actions
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        v.setOnClickPendingIntent(R.id.btn_feed,
                PendingIntent.getBroadcast(ctx, 0,
                        new Intent(ctx, FeedWidget.class).setAction(ACTION_TOGGLE_FEED), flags));
        v.setOnClickPendingIntent(R.id.btn_maint,
                PendingIntent.getBroadcast(ctx, 1,
                        new Intent(ctx, FeedWidget.class).setAction(ACTION_TOGGLE_MAINT), flags));

        mgr.updateAppWidget(widgetId, v);
    }

    private static void toggle(Context ctx, boolean isFeed) {
        String host = getLampHost(ctx);
        String base = "http://" + host;
        String endpoint = isFeed ? "/api/feed" : "/api/maintenance";
        try {
            JSONObject status = httpGet(ctx, base + endpoint + "/status");
            boolean active = status.optBoolean("active", false);
            httpPost(ctx, base + endpoint + (active ? "/stop" : "/start"));
        } catch (Exception e) {
            Log.w(TAG, "toggle failed: " + e.getMessage());
        }
    }

    private static String getLampHost(Context ctx) {
        SharedPreferences prefs = ctx.getSharedPreferences("k7_android_bridge", Context.MODE_PRIVATE);
        return prefs.getString("host", K7TcpClient.DEFAULT_HOST);
    }

    private static HttpURLConnection openConn(Context ctx, String urlStr) throws Exception {
        URL url = new URL(urlStr);
        ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm != null) {
            for (Network net : cm.getAllNetworks()) {
                NetworkCapabilities caps = cm.getNetworkCapabilities(net);
                if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                    return (HttpURLConnection) net.openConnection(url);
                }
            }
        }
        return (HttpURLConnection) url.openConnection();
    }

    private static JSONObject httpGet(Context ctx, String urlStr) throws Exception {
        HttpURLConnection conn = openConn(ctx, urlStr);
        conn.setConnectTimeout(3000);
        conn.setReadTimeout(3000);
        try {
            if (conn.getResponseCode() != 200) throw new Exception("HTTP " + conn.getResponseCode());
            try (InputStream in = conn.getInputStream();
                 ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                return new JSONObject(out.toString("UTF-8"));
            }
        } finally {
            conn.disconnect();
        }
    }

    private static void httpPost(Context ctx, String urlStr) throws Exception {
        HttpURLConnection conn = openConn(ctx, urlStr);
        conn.setConnectTimeout(3000);
        conn.setReadTimeout(3000);
        conn.setRequestMethod("POST");
        conn.setFixedLengthStreamingMode(0);
        conn.setDoOutput(true);
        try {
            conn.getOutputStream().close();
            int code = conn.getResponseCode();
            if (code != 200) throw new Exception("HTTP " + code);
        } finally {
            conn.disconnect();
        }
    }

    private static String formatSecs(int secs) {
        if (secs <= 0) return "";
        return String.format(Locale.ROOT, "%d:%02d", secs / 60, secs % 60);
    }
}
