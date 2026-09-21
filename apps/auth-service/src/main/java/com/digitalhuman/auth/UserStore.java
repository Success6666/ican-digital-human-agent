package com.digitalhuman.auth;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

@Component
public class UserStore {

    private final Map<String, UserAccount> usersByUsername = new ConcurrentHashMap<>();
    private final Map<String, UserAccount> usersById = new ConcurrentHashMap<>();

    public UserStore(PasswordEncoder passwordEncoder) {
        add("u-demo", "demo", "演示用户", "user", "demo123", passwordEncoder);
        add("u-admin", "admin", "管理员", "admin", "admin123", passwordEncoder);
    }

    public Optional<UserAccount> findByUsername(String username) {
        return Optional.ofNullable(usersByUsername.get(username));
    }

    public Optional<UserAccount> findById(String id) {
        return Optional.ofNullable(usersById.get(id));
    }

    private void add(
            String id,
            String username,
            String displayName,
            String role,
            String password,
            PasswordEncoder passwordEncoder
    ) {
        UserAccount account = new UserAccount(id, username, displayName, role, passwordEncoder.encode(password));
        usersByUsername.put(username, account);
        usersById.put(id, account);
    }
}
