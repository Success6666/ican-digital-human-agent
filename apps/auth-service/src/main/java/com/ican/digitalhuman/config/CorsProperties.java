package com.ican.digitalhuman.config;

import java.util.Arrays;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "security")
public record CorsProperties(String corsOrigins) {
    public List<String> origins() {
        if (corsOrigins == null || corsOrigins.isBlank()) {
            return List.of("http://localhost:5173");
        }
        return Arrays.stream(corsOrigins.split(","))
                .map(String::trim)
                .filter(value -> !value.isBlank())
                .toList();
    }
}
