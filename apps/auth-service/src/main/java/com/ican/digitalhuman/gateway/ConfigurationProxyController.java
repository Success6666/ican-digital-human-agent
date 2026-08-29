package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
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
}
