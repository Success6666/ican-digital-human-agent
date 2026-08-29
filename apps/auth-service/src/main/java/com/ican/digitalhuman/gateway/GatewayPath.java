package com.ican.digitalhuman.gateway;

import com.ican.digitalhuman.common.GatewayException;

/** Validates identifiers before they become fixed upstream path segments. */
final class GatewayPath {

    private GatewayPath() {
    }

    static String segment(String value) {
        if (value == null || value.isBlank() || value.length() > 128
                || !value.matches("[A-Za-z0-9._:-]+") || value.contains("..")) {
            throw new GatewayException(422, "参数无效");
        }
        return value;
    }

    static String query(String value) {
        if (value == null || value.isBlank() || value.length() > 128
                || !value.matches("[A-Za-z0-9._:-]+")) {
            throw new GatewayException(422, "参数无效");
        }
        return value;
    }
}
