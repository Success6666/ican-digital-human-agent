package com.digitalhuman.auth;

public record UserAccount(String id, String username, String displayName, String role, String passwordHash) {
    public UserAccount withoutPassword() {
        return new UserAccount(id, username, displayName, role, null);
    }
}
