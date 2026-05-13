package com.bitbarista.k7controller;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.JsPromptResult;
import android.webkit.JsResult;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;

import androidx.core.content.FileProvider;

import java.io.File;
import java.io.FileOutputStream;

public class MainActivity extends Activity {

    private WebView webView;
    private boolean pageLoaded = false;
    private ValueCallback<Uri[]> mFilePathCallback;
    private String mPendingSaveContent;
    private static final int FILE_CHOOSER_REQUEST = 1001;
    private static final int SAVE_JSON_REQUEST    = 1002;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        startService(new android.content.Intent(this, K7BridgeService.class));

        FrameLayout root = new FrameLayout(this);
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        root.setOnApplyWindowInsetsListener((View view, WindowInsets insets) -> {
            view.setPadding(0, insets.getSystemWindowInsetTop(), 0, insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                if (url != null && url.startsWith("http://127.0.0.1:8787")) {
                    pageLoaded = true;
                }
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(message)
                        .setPositiveButton("OK", (d, w) -> result.confirm())
                        .setOnCancelListener(d -> result.cancel())
                        .show();
                return true;
            }

            @Override
            public boolean onJsConfirm(WebView view, String url, String message, JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(message)
                        .setPositiveButton("Yes", (d, w) -> result.confirm())
                        .setNegativeButton("No", (d, w) -> result.cancel())
                        .setOnCancelListener(d -> result.cancel())
                        .show();
                return true;
            }

            @Override
            public boolean onJsPrompt(WebView view, String url, String message, String defaultValue, JsPromptResult result) {
                EditText input = new EditText(MainActivity.this);
                input.setText(defaultValue);
                input.setSelectAllOnFocus(true);
                new AlertDialog.Builder(MainActivity.this)
                        .setMessage(message)
                        .setView(input)
                        .setPositiveButton("OK", (d, w) -> result.confirm(input.getText().toString()))
                        .setNegativeButton("Cancel", (d, w) -> result.cancel())
                        .setOnCancelListener(d -> result.cancel())
                        .show();
                return true;
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> filePathCallback,
                    FileChooserParams fileChooserParams) {
                if (mFilePathCallback != null) {
                    mFilePathCallback.onReceiveValue(null);
                }
                mFilePathCallback = filePathCallback;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("application/json");
                startActivityForResult(Intent.createChooser(intent, "Choose file"), FILE_CHOOSER_REQUEST);
                return true;
            }
        });
        webView.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void openWifiSettings() {
                startActivity(new Intent(Settings.ACTION_WIFI_SETTINGS));
            }

            @JavascriptInterface
            public void saveJson(String filename, String content) {
                mPendingSaveContent = content;
                Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("application/json");
                intent.putExtra(Intent.EXTRA_TITLE, filename);
                startActivity(intent);
            }

            @JavascriptInterface
            public void shareJson(String filename, String content) {
                try {
                    File file = new File(getCacheDir(), filename);
                    try (FileOutputStream fos = new FileOutputStream(file)) {
                        fos.write(content.getBytes("UTF-8"));
                    }
                    Uri uri = FileProvider.getUriForFile(MainActivity.this,
                            getPackageName() + ".fileprovider", file);
                    Intent intent = new Intent(Intent.ACTION_SEND);
                    intent.setType("application/json");
                    intent.putExtra(Intent.EXTRA_STREAM, uri);
                    intent.putExtra(Intent.EXTRA_SUBJECT, filename);
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    startActivity(Intent.createChooser(intent, "Save or share " + filename));
                } catch (Exception e) {
                    Log.e("K7Main", "shareJson failed: " + e.getMessage());
                }
            }
        }, "K7Android");
        new Thread(() -> {
            Log.d("K7Main", "probe thread started");
            for (int i = 0; i < 40; i++) {
                try (java.net.Socket s = new java.net.Socket()) {
                    s.connect(new java.net.InetSocketAddress("127.0.0.1", 8787), 300);
                    Log.d("K7Main", "bridge ready after " + i + " retries, loading URL");
                    webView.post(() -> webView.loadUrl("http://127.0.0.1:8787/static/mobile.html"));
                    return;
                } catch (Exception e) {
                    Log.d("K7Main", "probe attempt " + i + " failed: " + e.getMessage());
                    try { Thread.sleep(250); } catch (InterruptedException ie) { return; }
                }
            }
            Log.d("K7Main", "probe exhausted retries, loading anyway");
            webView.post(() -> webView.loadUrl("http://127.0.0.1:8787/static/mobile.html"));
        }).start();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (mFilePathCallback != null) {
                Uri[] results = null;
                if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                    results = new Uri[]{data.getData()};
                }
                mFilePathCallback.onReceiveValue(results);
                mFilePathCallback = null;
            }
        } else if (requestCode == SAVE_JSON_REQUEST) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null && mPendingSaveContent != null) {
                try (java.io.OutputStream os = getContentResolver().openOutputStream(data.getData())) {
                    os.write(mPendingSaveContent.getBytes("UTF-8"));
                } catch (Exception e) {
                    Log.e("K7Main", "saveJson write failed: " + e.getMessage());
                }
            }
            mPendingSaveContent = null;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (pageLoaded && webView != null) {
            webView.evaluateJavascript("readFromDevice()", null);
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
    }
}
