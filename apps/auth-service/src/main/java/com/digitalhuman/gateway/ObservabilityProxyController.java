package com.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.digitalhuman.auth.AuthService;
import com.digitalhuman.auth.UserAccount;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/observability")
public class ObservabilityProxyController {

    private final AuthService authService;
    private final AgentGatewayClient agentGatewayClient;

    public ObservabilityProxyController(AuthService authService, AgentGatewayClient agentGatewayClient) {
        this.authService = authService;
        this.agentGatewayClient = agentGatewayClient;
    }

    @GetMapping("/health")
    public JsonNode health() {
        UserAccount current = user();
        return agentGatewayClient.get("/internal/observability/health", current.id(), current.username());
    }

    @GetMapping("/recent")
    public JsonNode recent(@RequestParam(defaultValue = "50") int limit) {
        UserAccount current = user();
        int safeLimit = Math.max(1, Math.min(limit, 200));
        return agentGatewayClient.get(
                "/internal/observability/recent?limit=" + safeLimit,
                current.id(),
                current.username()
        );
    }

    @GetMapping("/traces")
    public JsonNode traces(@RequestParam(defaultValue = "30") int limit) {
        UserAccount current = user();
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return agentGatewayClient.get(
                "/internal/observability/traces?limit=" + safeLimit,
                current.id(),
                current.username()
        );
    }

    @GetMapping("/traces/{traceId}")
    public JsonNode traceReplay(@PathVariable String traceId) {
        UserAccount current = user();
        String safeTraceId = encodePath(traceId);
        return agentGatewayClient.get(
                "/internal/observability/traces/" + safeTraceId,
                current.id(),
                current.username()
        );
    }

    private UserAccount user() {
        return authService.requireCurrentUser();
    }

    private String encodePath(String value) {
        return GatewayPath.segment(value);
    }
}
