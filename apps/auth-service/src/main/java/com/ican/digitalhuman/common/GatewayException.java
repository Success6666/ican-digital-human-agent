package com.ican.digitalhuman.common;

public class GatewayException extends RuntimeException {
    private final int status;

    public GatewayException(int status, String message) {
        super(message);
        this.status = status;
    }

    public int status() {
        return status;
    }
}
