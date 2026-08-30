package com.ican.digitalhuman.auth;

import com.ican.digitalhuman.auth.dto.LoginRequest;
import com.ican.digitalhuman.auth.dto.LoginResponse;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping(value = "/login", produces = MediaType.APPLICATION_JSON_VALUE)
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        return authService.login(request);
    }

    @PostMapping("/logout")
    public void logout() {
        authService.logout();
    }

    @GetMapping("/me")
    public LoginResponse.UserView me() {
        UserAccount account = authService.requireCurrentUser();
        return new LoginResponse.UserView(account.id(), account.username(), account.displayName(), account.role());
    }
}
