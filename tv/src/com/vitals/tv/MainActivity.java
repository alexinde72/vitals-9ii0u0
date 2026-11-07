package com.vitals.tv;

import android.app.Activity;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.util.Log;
import android.graphics.Bitmap;
import android.net.http.SslError;
import android.webkit.ConsoleMessage;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceResponse;
import android.webkit.ValueCallback;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** Full-screen WebView showing the Vitals dashboard in TV mode. The web app handles D-pad focus itself. */
public class MainActivity extends Activity {
    static final String URL = "https://alexinde72.github.io/vitals-9ii0u0/?tv=1";
    static final String OFFLINE = "<html><body style='background:#000;color:#c3c2b7;font-family:sans-serif;display:flex;"
        + "align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column'>"
        + "<div style='font-size:42px;font-weight:800;color:#f0efec;letter-spacing:4px'>VITALS</div>"
        + "<p style='font-size:22px'>No connection. Retrying in 30 seconds&hellip;</p></body></html>";

    private WebView web;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean showingOffline = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        web = new WebView(this);
        web.setBackgroundColor(Color.TRANSPARENT);
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " VitalsTV/1.0 Android TV");
        WebView.setWebContentsDebuggingEnabled(true);
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                Log.w("VitalsWeb", m.messageLevel() + " " + m.message() + " @" + m.sourceId() + ":" + m.lineNumber());
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) { Log.w("VitalsWeb", "page started " + url); }
            @Override
            public void onPageFinished(WebView view, String url) {
                Log.w("VitalsWeb", "page finished " + url);
                view.setBackgroundColor(Color.BLACK);
                if (!showingOffline) scheduleWatchdog();
            }
            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse r) {
                Log.w("VitalsWeb", "http " + r.getStatusCode() + " " + request.getUrl());
            }
            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                Log.w("VitalsWeb", "ssl error " + error);
                handler.cancel();
            }
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !request.getUrl().toString().startsWith("https://alexinde72.github.io/");
            }
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                Log.w("VitalsWeb", "error " + error.getErrorCode() + " " + error.getDescription() + " " + request.getUrl());
                if (request.isForMainFrame()) showOffline();
            }
        });
        setContentView(web);
        load();
    }

    private void load() {
        showingOffline = false;
        web.loadUrl(URL);
        web.requestFocus();
    }

    private int watchdogFails = 0;
    private final Runnable watchdog = new Runnable() {
        public void run() {
            if (showingOffline) return;
            // window.__frames is bumped by requestAnimationFrame in the page; it must keep growing
            web.evaluateJavascript("(function(){var a=window.__vf||0;return document.querySelector('.app')&&window.__frames>a?(window.__vf=window.__frames,'ok'):'stuck'})()",
                new ValueCallback<String>() {
                    public void onReceiveValue(String v) {
                        if (v != null && v.contains("ok")) { watchdogFails = 0; scheduleWatchdog(); return; }
                        watchdogFails++;
                        Log.w("VitalsWeb", "watchdog: page stuck (" + watchdogFails + "), reloading");
                        if (watchdogFails > 3) web.setLayerType(View.LAYER_TYPE_SOFTWARE, null);
                        load();
                    }
                });
        }
    };

    private void scheduleWatchdog() {
        handler.removeCallbacks(watchdog);
        handler.postDelayed(watchdog, 10000);
    }

    private void showOffline() {
        showingOffline = true;
        web.loadDataWithBaseURL(null, OFFLINE, "text/html", "utf-8", null);
        handler.removeCallbacksAndMessages(null);
        handler.postDelayed(new Runnable() { public void run() { if (online()) load(); else showOffline(); } }, 30000);
    }

    private boolean online() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        NetworkInfo ni = cm == null ? null : cm.getActiveNetworkInfo();
        return ni != null && ni.isConnected();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        // Back: let the web app move focus back to the menu / stop ambient mode first; exit only from the menu.
        if (event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
            if (event.getAction() == KeyEvent.ACTION_UP && !showingOffline) {
                web.evaluateJavascript("(window.tvBack && window.tvBack()) ? 'stay' : 'exit'", new ValueCallback<String>() {
                    public void onReceiveValue(String v) { if (v == null || !v.contains("stay")) finish(); }
                });
            } else if (event.getAction() == KeyEvent.ACTION_UP) {
                finish();
            }
            return true;
        }
        // Map the remote's Menu key to "start ambient mode"
        if (event.getKeyCode() == KeyEvent.KEYCODE_MENU && event.getAction() == KeyEvent.ACTION_UP) {
            web.evaluateJavascript("window.tvAmbient && window.tvAmbient()", null);
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
        web.evaluateJavascript("window.tvResume && window.tvResume()", null);
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        web.destroy();
        super.onDestroy();
    }
}
