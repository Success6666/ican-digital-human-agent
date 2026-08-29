package com.ican.digitalhuman.common;

import cn.dev33.satoken.exception.NotLoginException;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(NotLoginException.class)
    public ResponseEntity<ApiError> handleNotLogin(NotLoginException exception, HttpServletRequest request) {
        return error(401, "请先登录", request);
    }

    @ExceptionHandler({BizException.class, GatewayException.class})
    public ResponseEntity<ApiError> handleKnown(RuntimeException exception, HttpServletRequest request) {
        int status = exception instanceof BizException biz ? biz.status() : ((GatewayException) exception).status();
        return error(status, exception.getMessage(), request);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiError> handleValidation(MethodArgumentNotValidException exception, HttpServletRequest request) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getDefaultMessage() == null ? "请求参数无效" : error.getDefaultMessage())
                .orElse("请求参数无效");
        return error(400, message, request);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleUnexpected(Exception exception, HttpServletRequest request) {
        return error(500, "服务暂时不可用", request);
    }

    private ResponseEntity<ApiError> error(int status, String message, HttpServletRequest request) {
        String traceId = request.getHeader("X-Request-Id");
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString();
        }
        return ResponseEntity.status(status).body(new ApiError(status, message, traceId, Instant.now()));
    }
}
