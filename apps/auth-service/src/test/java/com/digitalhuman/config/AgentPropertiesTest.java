package com.digitalhuman.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Duration;
import org.junit.jupiter.api.Test;

class AgentPropertiesTest {

    @Test
    void productionRejectsPublicOrShortInternalTokens() {
        assertThatThrownBy(() -> properties("replace-with-a-long-random-token", "production"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("agent.internal-token");
        assertThatThrownBy(() -> properties("x".repeat(31), "prod"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("agent.internal-token");
    }

    @Test
    void productionAcceptsExplicitLongInternalToken() {
        AgentProperties properties = properties("agent-production-token-" + "x".repeat(32), "production");

        assertThat(properties.environment()).isEqualTo("production");
    }

    private static AgentProperties properties(String token, String environment) {
        return new AgentProperties(
                "http://127.0.0.1:8000",
                token,
                Duration.ofSeconds(1),
                Duration.ofSeconds(2),
                "/internal/realtime",
                64 * 1024,
                1_000,
                64 * 1024,
                4,
                environment);
    }
}
