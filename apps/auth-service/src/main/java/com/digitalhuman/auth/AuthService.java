package com.digitalhuman.auth;

import cn.dev33.satoken.stp.StpUtil;
import com.digitalhuman.common.BizException;
import com.digitalhuman.auth.dto.LoginRequest;
import com.digitalhuman.auth.dto.LoginResponse;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {

    private final UserStore userStore;
    private final PasswordEncoder passwordEncoder;

    public AuthService(UserStore userStore, PasswordEncoder passwordEncoder) {
        this.userStore = userStore;
        this.passwordEncoder = passwordEncoder;
    }

    public LoginResponse login(LoginRequest request) {
        UserAccount account = userStore.findByUsername(request.username())
                .filter(user -> passwordEncoder.matches(request.password(), user.passwordHash()))
                .orElseThrow(() -> new BizException(401, "用户名或密码错误"));
        StpUtil.login(account.id());
        return new LoginResponse(
                StpUtil.getTokenValue(),
                new LoginResponse.UserView(account.id(), account.username(), account.displayName(), account.role())
        );
    }

    public UserAccount requireCurrentUser() {
        StpUtil.checkLogin();
        String userId = StpUtil.getLoginIdAsString();
        return userStore.findById(userId)
                .orElseThrow(() -> new BizException(401, "登录用户不存在或已失效"));
    }

    public void logout() {
        StpUtil.logout();
    }
}
