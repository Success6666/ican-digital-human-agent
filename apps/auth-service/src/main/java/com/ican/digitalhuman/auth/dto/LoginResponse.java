package com.ican.digitalhuman.auth.dto;

public record LoginResponse(String token, UserView user) {
    public record UserView(String id, String username, String displayName, String role) {
    }
}
