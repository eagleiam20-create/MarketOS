
package com.marketos.app;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.view.KeyEvent;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebSettings;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Button;
import android.widget.ProgressBar;

public class MainActivity extends Activity {

    private WebView webView;
    private LinearLayout root;
    private LinearLayout errorPanel;
    private ProgressBar progressBar;

    // YAHAN APNI LIVE MARKETOS WEBSITE KA URL DALO
    private static final String MARKETOS_URL = "https://example.com";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);

        progressBar = new ProgressBar(
            this, null,
            android.R.attr.progressBarStyleHorizontal
        );
        progressBar.setIndeterminate(true);

        root.addView(progressBar, new LinearLayout.LayoutParams(
            -1, 4
        ));

        webView = new WebView(this);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadsImagesAutomatically(true);

        root.addView(webView, new LinearLayout.LayoutParams(
            -1, 0, 1
        ));

        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER);
        errorPanel.setPadding(32, 32, 32, 32);
        errorPanel.setVisibility(View.GONE);

        TextView message = new TextView(this);
        message.setText(
            "MarketOS load nahi ho saka. Internet aur website URL check karein."
        );
        message.setTextSize(17);
        message.setGravity(Gravity.CENTER);

        errorPanel.addView(message);

        Button retry = new Button(this);
        retry.setText("Retry");
        retry.setOnClickListener(v -> loadWebsite());

        errorPanel.addView(retry);

        root.addView(errorPanel, new LinearLayout.LayoutParams(
            -1, 0, 1
        ));

        setContentView(root);

        webView.setWebViewClient(new WebViewClient() {

            @Override
            public void onPageStarted(
                WebView view, String url,
                android.graphics.Bitmap favicon
            ) {
                progressBar.setVisibility(View.VISIBLE);
                errorPanel.setVisibility(View.GONE);
                webView.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progressBar.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error
            ) {
                if (request.isForMainFrame()) {
                    showError();
                }
            }
        });

        loadWebsite();
    }

    private void loadWebsite() {
        if (MARKETOS_URL.contains("example.com")) {
            showError();
            return;
        }

        errorPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        progressBar.setVisibility(View.VISIBLE);
        webView.loadUrl(MARKETOS_URL);
    }

    private void showError() {
        runOnUiThread(() -> {
            progressBar.setVisibility(View.GONE);
            webView.setVisibility(View.GONE);
            errorPanel.setVisibility(View.VISIBLE);
        });
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK
            && webView != null
            && webView.getVisibility() == View.VISIBLE
            && webView.canGoBack()) {
            webView.goBack();
            return true;
        }

        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }
}
