package com.digitalhuman.realtime;

import java.net.URI;

final class RealtimeRelaySupport {

    private RealtimeRelaySupport() {
    }

    static URI agentUri(String baseUrl, String path) {
        String normalizedBaseUrl = baseUrl == null ? "" : baseUrl.trim();
        String scheme = normalizedBaseUrl.startsWith("https://") ? "wss://" : "ws://";
        String authority = normalizedBaseUrl.replaceFirst("^https?://", "")
                .replaceFirst("/+$", "");
        String requestedPath = path == null || path.isBlank() ? "/internal/realtime" : path.trim();
        String normalizedPath = requestedPath.startsWith("/") ? requestedPath : "/" + requestedPath;
        return URI.create(scheme + authority + normalizedPath);
    }
}
