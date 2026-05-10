package com.bitbarista.k7controller;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

public class K7BridgeService extends Service {

    static final String CHANNEL_ID = "k7_bridge";
    private static final int NOTIF_ID = 1;

    private LocalBridgeServer server;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (server == null) {
            server = new LocalBridgeServer(this);
            server.start();
        }
        startForeground(NOTIF_ID, buildNotification());
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (server != null) {
            server.stop();
            server = null;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            NotificationChannel chan = new NotificationChannel(
                    CHANNEL_ID, "K7 Controller", NotificationManager.IMPORTANCE_LOW);
            chan.setShowBadge(false);
            nm.createNotificationChannel(chan);
            return new Notification.Builder(this, CHANNEL_ID)
                    .setContentTitle("K7 Controller")
                    .setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setOngoing(true)
                    .build();
        } else {
            return new Notification.Builder(this)
                    .setContentTitle("K7 Controller")
                    .setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setPriority(Notification.PRIORITY_LOW)
                    .setOngoing(true)
                    .build();
        }
    }
}
