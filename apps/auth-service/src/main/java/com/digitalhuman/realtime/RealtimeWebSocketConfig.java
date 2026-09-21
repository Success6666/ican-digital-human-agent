package com.digitalhuman.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.auth.AuthService;
import com.digitalhuman.config.AgentProperties;
import com.digitalhuman.config.CorsProperties;
import java.util.List;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class RealtimeWebSocketConfig implements WebSocketConfigurer {

    private final RealtimeWebSocketHandler handler;
    private final RealtimeHandshakeInterceptor interceptor;
    private final List<String> allowedOrigins;

    public RealtimeWebSocketConfig(
            AgentProperties properties,
            ObjectMapper objectMapper,
            AuthService authService,
            CorsProperties corsProperties
    ) {
        // Construct the transport collaborators here instead of injecting
        // beans declared by this same configuration class. That keeps the
        // WebSocket bootstrap free of a configuration-bean cycle.
        this.handler = new RealtimeWebSocketHandler(properties, objectMapper);
        this.interceptor = new RealtimeHandshakeInterceptor(authService, objectMapper);
        this.allowedOrigins = corsProperties.origins();
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, "/api/realtime")
                .addInterceptors(interceptor)
                .setAllowedOrigins(allowedOrigins.toArray(String[]::new));
    }
}
