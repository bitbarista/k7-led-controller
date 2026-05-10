package com.bitbarista.k7controller;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.SystemClock;
import android.util.Log;
import android.view.View;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

public class FeedWidget extends AppWidgetProvider {

    private static final String TAG = "K7FeedWidget";
    static final String ACTION_TOGGLE_FEED  = "com.bitbarista.k7controller.TOGGLE_FEED";
    static final String ACTION_TOGGLE_MAINT = "com.bitbarista.k7controller.TOGGLE_MAINT";

    @Override
    public void onUpdate(Context ctx, AppWidgetManager mgr, int[] ids) {
        for (int id : ids) applyStoredState(ctx, mgr, id, false);
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
                boolean lampOffline = doToggle(ctx, isFeed);
                AppWidgetManager mgr = AppWidgetManager.getInstance(ctx);
                int[] ids = mgr.getAppWidgetIds(new ComponentName(ctx, FeedWidget.class));
                for (int id : ids) applyStoredState(ctx, mgr, id, lampOffline);
            } finally {
                result.finish();
            }
        }).start();
    }

    private static void applyStoredState(Context ctx, AppWidgetManager mgr, int widgetId, boolean lampOffline) {
        SharedPreferences prefs = ctx.getSharedPreferences("k7_android_bridge", Context.MODE_PRIVATE);

        boolean feedActive = prefs.getBoolean("feed_active", false);
        int feedRemaining = 0;
        if (feedActive) {
            int duration = prefs.getInt("feed_duration", 10 * 60);
            feedRemaining = duration - (int) ((System.currentTimeMillis() - prefs.getLong("feed_started_at", 0)) / 1000);
            if (feedRemaining <= 0) { feedActive = false; feedRemaining = 0; }
        }

        boolean maintActive = prefs.getBoolean("maint_active", false);
        int maintRemaining = 0;
        if (maintActive) {
            int duration = prefs.getInt("maint_duration", 60 * 60);
            maintRemaining = duration - (int) ((System.currentTimeMillis() - prefs.getLong("maint_started_at", 0)) / 1000);
            if (maintRemaining <= 0) { maintActive = false; maintRemaining = 0; }
        }

        RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget_feed);

        v.setTextViewText(R.id.btn_feed, "Feed");
        v.setTextColor(R.id.btn_feed, feedActive ? 0xFFFFFFFF : 0xFFB0B8C4);
        v.setInt(R.id.btn_feed, "setBackgroundResource",
                feedActive ? R.drawable.widget_btn_feed_active : R.drawable.widget_btn);

        v.setTextViewText(R.id.btn_maint, "Maintenance");
        v.setTextColor(R.id.btn_maint, maintActive ? 0xFFFFFFFF : 0xFFB0B8C4);
        v.setInt(R.id.btn_maint, "setBackgroundResource",
                maintActive ? R.drawable.widget_btn_maint_active : R.drawable.widget_btn);

        // Chronometer countdown timers (self-ticking, no widget refresh needed)
        boolean showFeedTimer = feedActive && feedRemaining > 0;
        boolean showMaintTimer = maintActive && maintRemaining > 0;
        v.setViewVisibility(R.id.timer_row, (showFeedTimer || showMaintTimer) ? View.VISIBLE : View.GONE);

        if (showFeedTimer) {
            long base = SystemClock.elapsedRealtime() + feedRemaining * 1000L;
            v.setChronometer(R.id.feed_timer, base, null, true);
            v.setBoolean(R.id.feed_timer, "setCountDown", true);
            v.setViewVisibility(R.id.feed_timer, View.VISIBLE);
        } else {
            v.setViewVisibility(R.id.feed_timer, View.GONE);
        }

        if (showMaintTimer) {
            long base = SystemClock.elapsedRealtime() + maintRemaining * 1000L;
            v.setChronometer(R.id.maint_timer, base, null, true);
            v.setBoolean(R.id.maint_timer, "setCountDown", true);
            v.setViewVisibility(R.id.maint_timer, View.VISIBLE);
        } else {
            v.setViewVisibility(R.id.maint_timer, View.GONE);
        }


        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        v.setOnClickPendingIntent(R.id.btn_feed,
                PendingIntent.getBroadcast(ctx, 0,
                        new Intent(ctx, FeedWidget.class).setAction(ACTION_TOGGLE_FEED), flags));
        v.setOnClickPendingIntent(R.id.btn_maint,
                PendingIntent.getBroadcast(ctx, 1,
                        new Intent(ctx, FeedWidget.class).setAction(ACTION_TOGGLE_MAINT), flags));

        mgr.updateAppWidget(widgetId, v);
    }

    // Channel profiles matching Effects.cpp firmware constants
    private static final int[] FEED_MINI  = {80, 10, 10,  0,  0, 0};
    private static final int[] FEED_PRO   = {80, 10, 40, 80, 10, 0};
    private static final int[] MAINT_MINI = {100, 40, 50,  0,  0, 0};
    private static final int[] MAINT_PRO  = {100, 30, 55, 15, 40, 5};
    private static final int MAINT_INTENSITY = 70; // firmware default gMaintenanceIntensity

    // Returns true if the lamp was unreachable
    private static boolean doToggle(Context ctx, boolean isFeed) {
        SharedPreferences prefs = ctx.getSharedPreferences("k7_android_bridge", Context.MODE_PRIVATE);
        String host = prefs.getString("host", K7TcpClient.DEFAULT_HOST);
        int port = prefs.getInt("port", K7TcpClient.DEFAULT_PORT);
        String key = isFeed ? "feed" : "maint";
        String other = isFeed ? "maint" : "feed";
        int defaultSecs = isFeed ? 10 * 60 : 30 * 60;
        boolean active = prefs.getBoolean(key + "_active", false);
        boolean isPro = "k7pro".equals(prefs.getString("device", "k7mini"));
        int master = prefs.getInt("master", 100);
        K7TcpClient client = new K7TcpClient(ctx, host, port, 3000);
        try {
            if (!active) {
                int[] base = isFeed
                        ? (isPro ? FEED_PRO : FEED_MINI)
                        : (isPro ? MAINT_PRO : MAINT_MINI);
                int[] channels = new int[K7TcpClient.CHANNELS];
                for (int i = 0; i < K7TcpClient.CHANNELS; i++) {
                    int v = base[i];
                    if (!isFeed) v = v * MAINT_INTENSITY / 100;
                    channels[i] = v * master / 100;
                }
                client.hand(channels);
                prefs.edit()
                        .putBoolean(other + "_active", false)
                        .putBoolean(key + "_active", true)
                        .putLong(key + "_started_at", System.currentTimeMillis())
                        .putInt(key + "_duration", defaultSecs)
                        .apply();
            } else {
                restoreAuto(client, prefs);
                prefs.edit().putBoolean(key + "_active", false).apply();
            }
            return false;
        } catch (Exception e) {
            Log.w(TAG, "toggle failed: " + e.getMessage());
            return true;
        }
    }

    private static void restoreAuto(K7TcpClient client, SharedPreferences prefs) throws Exception {
        String stateJson = prefs.getString("state", null);
        if (stateJson == null) return;
        JSONObject state = new JSONObject(stateJson);
        JSONArray scheduleArr = state.getJSONArray("schedule");
        JSONArray manualArr = state.getJSONArray("manual");
        int master = prefs.getInt("master", 100);

        int[][] schedule = new int[K7TcpClient.SLOTS][8];
        for (int h = 0; h < K7TcpClient.SLOTS; h++) {
            JSONArray row = scheduleArr.optJSONArray(h);
            for (int c = 0; c < 8; c++)
                schedule[h][c] = K7TcpClient.clamp(row == null ? 0 : row.optInt(c));
        }
        // Apply master brightness
        for (int h = 0; h < K7TcpClient.SLOTS; h++)
            for (int c = 2; c < 8; c++)
                schedule[h][c] = schedule[h][c] * master / 100;

        int[] manual = new int[K7TcpClient.CHANNELS];
        for (int i = 0; i < K7TcpClient.CHANNELS; i++)
            manual[i] = K7TcpClient.clamp(manualArr.optInt(i)) * master / 100;

        client.push(manual, schedule, true);
    }

}
