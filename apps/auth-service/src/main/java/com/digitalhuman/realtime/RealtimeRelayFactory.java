package com.digitalhuman.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.config.AgentProperties;
import java.util.Objects;
import org.springframework.web.socket.WebSocketSession;

@FunctionalInterface
interface RealtimeRelayFactory {

    AgentRealtimeRelay create(
            WebSocketSession browser,
            String userId,
            String userName,
            AgentProperties properties,
            ObjectMapper objectMapper
    );

    static RealtimeRelayFactory defaultFactory() {
        return AgentRealtimeRelay::new;
    }

    static RealtimeRelayFactory require(RealtimeRelayFactory factory) {
        return Objects.requireNonNull(factory, "factory");
    }
}
