package com.ican.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import com.ican.digitalhuman.common.BizException;
import org.junit.jupiter.api.Test;

class ConfigurationProxyControllerTest {

    @Test
    void adminUpdateIsForwardedWithRole() {
        AuthService authService = mock(AuthService.class);
        AgentGatewayClient gatewayClient = mock(AgentGatewayClient.class);
        UserAccount account = new UserAccount("u-admin", "admin", "管理员", "admin", null);
        when(authService.requireCurrentUser()).thenReturn(account);
        var body = new ObjectMapper().createObjectNode().put("defaultProvider", "mock");

        new ConfigurationProxyController(authService, gatewayClient).update(body);

        verify(gatewayClient).patch("/internal/configuration", body, "u-admin", "admin", "admin");
    }

    @Test
    void nonAdminUpdateIsRejectedBeforeGatewayCall() {
        AuthService authService = mock(AuthService.class);
        AgentGatewayClient gatewayClient = mock(AgentGatewayClient.class);
        when(authService.requireCurrentUser())
                .thenReturn(new UserAccount("u-demo", "demo", "普通用户", "user", null));
        var body = new ObjectMapper().createObjectNode().put("defaultProvider", "mock");

        assertThatThrownBy(() -> new ConfigurationProxyController(authService, gatewayClient).update(body))
                .isInstanceOf(BizException.class)
                .hasMessage("仅管理员可修改后台配置");
        verifyNoInteractions(gatewayClient);
    }
}
