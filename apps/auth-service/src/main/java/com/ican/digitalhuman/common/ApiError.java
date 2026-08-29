package com.ican.digitalhuman.common;

import java.time.Instant;

public record ApiError(int status, String message, String traceId, Instant timestamp) {
}
