package com.ican.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.ican.digitalhuman.common.GatewayException;
import org.junit.jupiter.api.Test;

class GatewayPathTest {

    @Test
    void acceptsGeneratedIdentifiers() {
        assertThat(GatewayPath.segment("mock-0123_abcd:1")).isEqualTo("mock-0123_abcd:1");
        assertThat(GatewayPath.query("knowledge.v1")).isEqualTo("knowledge.v1");
    }

    @Test
    void rejectsPathAndQueryInjectionCharacters() {
        assertThatThrownBy(() -> GatewayPath.segment("../internal/health"))
                .isInstanceOf(GatewayException.class)
                .hasMessage("参数无效");
        assertThatThrownBy(() -> GatewayPath.query("default&admin=true"))
                .isInstanceOf(GatewayException.class)
                .hasMessage("参数无效");
    }
}
