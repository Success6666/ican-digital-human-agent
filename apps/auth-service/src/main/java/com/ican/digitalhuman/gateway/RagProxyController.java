package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/rag")
public class RagProxyController {

    private final AuthService authService;
    private final AgentGatewayClient agentGatewayClient;

    public RagProxyController(AuthService authService, AgentGatewayClient agentGatewayClient) {
        this.authService = authService;
        this.agentGatewayClient = agentGatewayClient;
    }

    @GetMapping("/health")
    public JsonNode health() {
        return agentGatewayClient.get("/internal/rag/health", user().id(), user().username());
    }

    @PostMapping("/ingest")
    public JsonNode ingest(@RequestBody JsonNode body) {
        return agentGatewayClient.post("/internal/rag/ingest", body, user().id(), user().username());
    }

    @PostMapping("/search")
    public JsonNode search(@RequestBody JsonNode body) {
        return agentGatewayClient.post("/internal/rag/search", body, user().id(), user().username());
    }

    @DeleteMapping("/documents/{documentId}")
    public JsonNode delete(
            @PathVariable String documentId,
            @RequestParam(defaultValue = "default") String collection
    ) {
        UserAccount current = user();
        String path = "/internal/rag/documents/" + encodePath(documentId)
                + "?collection=" + encodeQuery(collection);
        return agentGatewayClient.deleteWithBody(path, current.id(), current.username());
    }

    private UserAccount user() {
        return authService.requireCurrentUser();
    }

    private String encodePath(String value) {
        return GatewayPath.segment(value);
    }

    private String encodeQuery(String value) {
        return GatewayPath.query(value);
    }
}
