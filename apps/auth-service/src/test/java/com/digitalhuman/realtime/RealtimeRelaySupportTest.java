package com.digitalhuman.realtime;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import org.junit.jupiter.api.Test;

class RealtimeRelaySupportTest {

    @Test
    void normalizesTransportSchemeAndTrailingSlashes() {
        URI secure = RealtimeRelaySupport.agentUri(
                "https://agent.internal///", "internal/realtime");
        URI plain = RealtimeRelaySupport.agentUri(
                "http://agent.internal", "/internal/realtime");

        assertThat(secure.toString()).isEqualTo("wss://agent.internal/internal/realtime");
        assertThat(plain.toString()).isEqualTo("ws://agent.internal/internal/realtime");
    }

    @Test
    void suppliesDefaultPathWhenConfigurationIsBlank() {
        assertThat(RealtimeRelaySupport.agentUri("http://agent.internal/", " ").toString())
                .isEqualTo("ws://agent.internal/internal/realtime");
    }
}
