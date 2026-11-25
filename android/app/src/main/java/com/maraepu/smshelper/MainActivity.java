package com.maraepu.smshelper;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.webkit.WebViewAssetLoader;

import java.net.URLEncoder;

/**
 * 마래푸중앙부동산 문자 도우미 — 안드로이드 껍데기(WebView 래퍼).
 * 앱 안에 들어 있는 웹 파일을 https://appassets.androidplatform.net 으로 열어
 * 오프라인에서도 그대로 동작하고, 클립보드·localStorage도 브라우저와 같게 쓴다.
 */
public class MainActivity extends Activity {

    private static final String START_URL = "https://appassets.androidplatform.net/assets/www/index.html";

    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(webView);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setTextZoom(100);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        webView.setBackgroundColor(0xFFF6F7FB);
        webView.setOverScrollMode(WebView.OVER_SCROLL_NEVER);

        final WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(Uri.parse(url));
            }
        });

        // 복사·문자 앱 열기 통로 (안드로이드 앱 껍데기에서만 생긴다)
        webView.addJavascriptInterface(new CopyBridge(), "AndroidCopy");
        webView.addJavascriptInterface(new SmsBridge(), "AndroidSms");

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            webView.loadUrl(START_URL);
        }
    }

    /** 문자 앱·전화·메일은 안드로이드 앱으로 넘기고, 앱 안 페이지는 WebView에서 그대로 연다. */
    private boolean handleUrl(Uri uri) {
        if (uri == null) return false;
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();

        if ("sms".equals(scheme) || "smsto".equals(scheme) || "mms".equals(scheme)) {
            openSms(uri);
            return true;
        }
        if ("tel".equals(scheme)) {
            try {
                startActivity(new Intent(Intent.ACTION_DIAL, uri));
            } catch (Exception e) {
                toast("전화 앱을 열 수 없어요");
            }
            return true;
        }
        if ("mailto".equals(scheme)) {
            try {
                startActivity(new Intent(Intent.ACTION_SENDTO, uri));
            } catch (Exception e) {
                toast("메일 앱을 열 수 없어요");
            }
            return true;
        }
        if ("https".equals(scheme) && "appassets.androidplatform.net".equals(uri.getHost())) {
            return false; // 앱 안 페이지 — WebView가 그대로 연다
        }
        if ("http".equals(scheme) || "https".equals(scheme)) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
            } catch (Exception e) {
                toast("브라우저를 열 수 없어요");
            }
            return true;
        }
        return false;
    }

    /**
     * 웹 쪽은 아이폰용 "sms:&body=..." 형태를 쓴다. 안드로이드는 이 형태를 모르는 앱이 많아
     * 본문을 뽑아 "sms:?body=..." 로 바꿔 기본 문자 앱에 넘긴다.
     */
    private void openSms(Uri uri) {
        String s = uri.toString();
        String body = null;
        int i = s.indexOf("body=");
        if (i >= 0) {
            body = Uri.decode(s.substring(i + 5));
        }
        Uri target;
        if (body != null && body.length() > 0) {
            target = Uri.parse("sms:?body=" + URLEncoder.encode(body));
        } else {
            target = Uri.parse("sms:");
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, target);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
        } catch (Exception e1) {
            // 일부 기기는 sms:?body= 를 받지 않는다 — 받는 사람 없이 본문만 넘기는 방식으로 한 번 더
            try {
                Intent alt = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:"));
                if (body != null) alt.putExtra("sms_body", body);
                startActivity(alt);
            } catch (Exception e2) {
                toast("문자 앱을 열 수 없어요. 본문을 복사해 붙여넣어 주세요.");
            }
        }
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    }

    public class CopyBridge {
        @JavascriptInterface
        public void copy(String text) {
            try {
                ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                if (cm != null) {
                    cm.setPrimaryClip(ClipData.newPlainText("문자", text));
                }
            } catch (Exception ignored) {
            }
        }
    }

    /** 문자 앱 열기 — 웹에서는 sms: 링크로 하지만, 앱 안에서는 인텐트를 직접 띄우는 편이 확실하다. */
    public class SmsBridge {
        @JavascriptInterface
        public void open(final String text) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    Uri target = Uri.parse("sms:?body=" + URLEncoder.encode(text == null ? "" : text));
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, target));
                    } catch (Exception e1) {
                        try {
                            Intent alt = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:"));
                            alt.putExtra("sms_body", text);
                            startActivity(alt);
                        } catch (Exception e2) {
                            toast("문자 앱을 열 수 없어요. 본문을 복사해 붙여넣어 주세요.");
                        }
                    }
                }
            });
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) webView.saveState(outState);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
