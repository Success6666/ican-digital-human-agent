package com.digitalhuman.realtime;

import java.nio.charset.StandardCharsets;

/** Immutable browser-to-Agent frame held by the bounded relay queue. */
record RealtimeOutboundFrame(byte[] payload, boolean binary) {

    static RealtimeOutboundFrame text(String value) {
        return new RealtimeOutboundFrame(value.getBytes(StandardCharsets.UTF_8), false);
    }

    static RealtimeOutboundFrame binary(byte[] value) {
        return new RealtimeOutboundFrame(value.clone(), true);
    }

    int bytes() {
        return payload.length;
    }
}
