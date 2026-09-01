package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/evaluation")
public class EvaluationProxyController {

    private final AuthService authService;
    private final AgentGatewayClient agentGatewayClient;

    public EvaluationProxyController(AuthService authService, AgentGatewayClient agentGatewayClient) {
        this.authService = authService;
        this.agentGatewayClient = agentGatewayClient;
    }

    @GetMapping("/overview")
    public JsonNode overview() {
        return agentGatewayClient.get("/internal/evaluation/overview", user().id(), user().username());
    }

    @GetMapping("/datasets")
    public JsonNode datasets() {
        return agentGatewayClient.get("/internal/evaluation/datasets", user().id(), user().username());
    }

    @PostMapping("/datasets/{datasetId}/run")
    public JsonNode runDataset(@PathVariable String datasetId, @RequestBody JsonNode body) {
        UserAccount current = user();
        String safeDatasetId = GatewayPath.segment(datasetId);
        return agentGatewayClient.post(
                "/internal/evaluation/datasets/" + safeDatasetId + "/run",
                body,
                current.id(),
                current.username()
        );
    }

    @PostMapping("/runs")
    public JsonNode recordRun(@RequestBody JsonNode body) {
        UserAccount current = user();
        return agentGatewayClient.post("/internal/evaluation/runs", body, current.id(), current.username());
    }

    @GetMapping("/runs")
    public JsonNode runs(@RequestParam(defaultValue = "50") int limit) {
        UserAccount current = user();
        int safeLimit = Math.max(1, Math.min(limit, 200));
        return agentGatewayClient.get(
                "/internal/evaluation/runs?limit=" + safeLimit,
                current.id(),
                current.username()
        );
    }

    @GetMapping("/runs/{runId}")
    public JsonNode runDetail(@org.springframework.web.bind.annotation.PathVariable String runId) {
        UserAccount current = user();
        String safeRunId = GatewayPath.segment(runId);
        return agentGatewayClient.get(
                "/internal/evaluation/runs/" + safeRunId,
                current.id(),
                current.username()
        );
    }

    private UserAccount user() {
        return authService.requireCurrentUser();
    }
}
