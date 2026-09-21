package com.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;

/** Tracks bounded upstream SSE metadata for a gateway-generated error frame. */
final class SseStreamEnvelope {

    private static final int MAX_PENDING_CHARS = 256 * 1024;
    private static final int MAX_IDENTIFIER_LENGTH = 128;
    private static final long MAX_UPSTREAM_SEQUENCE = 1_000_000_000L;

    private String traceId;
    private String runId;
    private boolean traceLocked;
    private boolean runLocked;
    private long sequence;
    private final StringBuilder pending = new StringBuilder();

    private SseStreamEnvelope(String traceId, String runId) {
        this.traceId = traceId;
        this.runId = runId;
    }

    static SseStreamEnvelope create(JsonNode body) {
        String requestedRunId = body == null ? null : body.path("runId").asText(null);
        SseStreamEnvelope envelope = new SseStreamEnvelope(
                UUID.randomUUID().toString(),
                sanitizeIdentifier(requestedRunId, UUID.randomUUID().toString())
        );
        envelope.runLocked = requestedRunId != null && !requestedRunId.isBlank();
        return envelope;
    }

    String traceId() {
        return traceId;
    }

    String runId() {
        return runId;
    }

    long nextSequence() {
        sequence += 1;
        return sequence;
    }

    String eventId() {
        return traceId + ":" + sequence;
    }

    void observe(String chunk, ObjectMapper objectMapper) {
        pending.append(chunk);
        int boundary;
        while ((boundary = frameBoundary(pending)) >= 0) {
            int delimiterLength = pending.substring(boundary).startsWith("\r\n\r\n") ? 4 : 2;
            String frame = pending.substring(0, boundary);
            pending.delete(0, boundary + delimiterLength);
            observeFrame(frame, objectMapper);
        }
        if (pending.length() > MAX_PENDING_CHARS) {
            // A malformed upstream frame must not grow the gateway heap
            // indefinitely while we wait for its closing delimiter.
            pending.setLength(0);
        }
    }

    private void observeFrame(String frame, ObjectMapper objectMapper) {
        String data = null;
        for (String line : frame.split("\\r?\\n")) {
            if (line.startsWith("data:")) {
                data = line.substring("data:".length()).trim();
                break;
            }
        }
        if (data == null || data.isBlank()) {
            return;
        }
        try {
            JsonNode payload = objectMapper.readTree(data);
            if (payload == null || !payload.isObject()) {
                return;
            }
            JsonNode upstreamRunId = payload.get("runId");
            if (!runLocked && upstreamRunId != null && upstreamRunId.isTextual()) {
                runId = sanitizeIdentifier(upstreamRunId.asText(), runId);
                runLocked = true;
            }
            JsonNode upstreamTraceId = payload.get("traceId");
            if (!traceLocked && upstreamTraceId != null && upstreamTraceId.isTextual()) {
                traceId = sanitizeIdentifier(upstreamTraceId.asText(), traceId);
                traceLocked = true;
            }
            JsonNode upstreamSequence = payload.get("seq");
            if (upstreamSequence != null && upstreamSequence.canConvertToLong()) {
                long value = upstreamSequence.asLong();
                if (value >= 0 && value <= MAX_UPSTREAM_SEQUENCE) {
                    sequence = Math.max(sequence, value);
                } else {
                    sequence += 1;
                }
            } else {
                sequence += 1;
            }
        } catch (Exception ignored) {
            // Keep forwarding opaque upstream frames; generated error metadata
            // remains available if the payload is malformed.
        }
    }

    private static int frameBoundary(StringBuilder value) {
        int lf = value.indexOf("\n\n");
        int crlf = value.indexOf("\r\n\r\n");
        if (lf < 0) {
            return crlf;
        }
        if (crlf < 0) {
            return lf;
        }
        return Math.min(lf, crlf);
    }

    private static String sanitizeIdentifier(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        String clean = value.replaceAll("[^A-Za-z0-9._:-]", "_");
        if (clean.isBlank()) {
            return fallback;
        }
        return clean.substring(0, Math.min(clean.length(), MAX_IDENTIFIER_LENGTH));
    }
}
