package com.ican.digitalhuman.realtime;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;

/** Bounded accumulator for fragmented upstream WebSocket messages. */
final class RealtimeInboundBuffer {

    private final int maxBytes;
    private StringBuilder text = new StringBuilder();
    private byte[] binary = new byte[0];

    RealtimeInboundBuffer(int maxBytes) {
        if (maxBytes < 1) {
            throw new IllegalArgumentException("maxBytes must be positive");
        }
        this.maxBytes = maxBytes;
    }

    boolean appendText(CharSequence data, boolean last, Consumer<String> complete) {
        if (data == null || complete == null) {
            return false;
        }
        int size = text.toString().getBytes(StandardCharsets.UTF_8).length
                + data.length() * 4;
        if (size > maxBytes) {
            return false;
        }
        text.append(data);
        if (last) {
            String payload = text.toString();
            text = new StringBuilder();
            complete.accept(payload);
        }
        return true;
    }

    boolean appendBinary(ByteBuffer data, boolean last, Consumer<byte[]> complete) {
        if (data == null || complete == null) {
            return false;
        }
        int nextSize = binary.length + data.remaining();
        if (nextSize > maxBytes) {
            return false;
        }
        byte[] next = new byte[nextSize];
        System.arraycopy(binary, 0, next, 0, binary.length);
        data.get(next, binary.length, data.remaining());
        binary = next;
        if (last) {
            complete.accept(binary);
            binary = new byte[0];
        }
        return true;
    }
}
