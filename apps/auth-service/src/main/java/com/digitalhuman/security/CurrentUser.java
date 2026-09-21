package com.digitalhuman.security;

public record CurrentUser(String id, String username, String displayName, String role) {
}
