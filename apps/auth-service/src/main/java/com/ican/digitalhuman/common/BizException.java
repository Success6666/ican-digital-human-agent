package com.ican.digitalhuman.common;

public class BizException extends RuntimeException {
    private final int status;

    public BizException(int status, String message) {
        super(message);
        this.status = status;
    }

    public int status() {
        return status;
    }
}
