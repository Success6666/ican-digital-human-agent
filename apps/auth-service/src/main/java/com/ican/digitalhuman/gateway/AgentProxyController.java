package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api")
public class AgentProxyController {

    private final AuthService authService;
    private final AgentGatewayClient agentGatewayClient;

    public AgentProxyController(AuthService authService, AgentGatewayClient agentGatewayClient) {
        this.authService = authService;
        this.agentGatewayClient = agentGatewayClient;
    }

    @GetMapping("/providers")
    public JsonNode providers() {
        return agentGatewayClient.get("/internal/providers", user().id(), user().username());
    }

    @PostMapping("/sessions")
    public JsonNode createSession(@RequestBody JsonNode body) {
        UserAccount current = user();
        return agentGatewayClient.post("/internal/sessions", body, current.id(), current.username());
    }

    @DeleteMapping("/sessions/{sessionId}")
    public void closeSession(@PathVariable String sessionId) {
        UserAccount current = user();
        agentGatewayClient.delete("/internal/sessions/" + encodePath(sessionId), current.id(), current.username());
    }

    @PostMapping("/sessions/{sessionId}/interrupt")
    public JsonNode interruptSession(
            @PathVariable String sessionId,
            @RequestBody(required = false) JsonNode body) {
        UserAccount current = user();
        return agentGatewayClient.post(
                "/internal/sessions/" + encodePath(sessionId) + "/interrupt",
                body,
                current.id(),
                current.username()
        );
    }

    @PostMapping("/chat")
    public JsonNode chat(@RequestBody JsonNode body) {
        UserAccount current = user();
        return agentGatewayClient.post("/internal/chat", body, current.id(), current.username());
    }

    @GetMapping("/profile")
    public JsonNode profile() {
        UserAccount current = user();
        return agentGatewayClient.get("/internal/profile", current.id(), current.username());
    }

    @PatchMapping("/profile")
    public JsonNode updateProfile(@RequestBody JsonNode body) {
        UserAccount current = user();
        return agentGatewayClient.patch("/internal/profile", body, current.id(), current.username(), current.role());
    }

    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> chatStream(@RequestBody JsonNode body) {
        UserAccount current = user();
        StreamingResponseBody stream = output -> agentGatewayClient.stream(
                "/internal/chat/stream", body, current.id(), current.username(), output);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .header("Cache-Control", "no-cache")
                .header("X-Accel-Buffering", "no")
                .body(stream);
    }

    private UserAccount user() {
        return authService.requireCurrentUser();
    }

    private String encodePath(String value) {
        return GatewayPath.segment(value);
    }
}
