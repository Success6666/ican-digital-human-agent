package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import com.ican.digitalhuman.common.BizException;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/configuration")
public class ConfigurationProxyController {

    private final AuthService authService;
    private final AgentGatewayClient agentGatewayClient;

    public ConfigurationProxyController(AuthService authService, AgentGatewayClient agentGatewayClient) {
        this.authService = authService;
        this.agentGatewayClient = agentGatewayClient;
    }

    @GetMapping
    public JsonNode view() {
        UserAccount current = authService.requireCurrentUser();
        return agentGatewayClient.get("/internal/configuration", current.id(), current.username());
    }

    @PatchMapping
    public JsonNode update(@RequestBody JsonNode body) {
        UserAccount current = authService.requireCurrentUser();
        if (!"admin".equals(current.role())) {
            throw new BizException(403, "仅管理员可修改后台配置");
        }
        return agentGatewayClient.patch(
                "/internal/configuration", body, current.id(), current.username(), current.role());
    }
}
