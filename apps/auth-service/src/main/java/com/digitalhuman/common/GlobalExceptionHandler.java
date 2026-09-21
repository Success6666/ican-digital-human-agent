package com.digitalhuman.common;

import cn.dev33.satoken.exception.NotLoginException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;
import org.springframework.http.MediaType;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private final ObjectMapper objectMapper;

    public GlobalExceptionHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @ExceptionHandler(NotLoginException.class)
    public void handleNotLogin(
            NotLoginException exception,
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        writeError(response, 401, "请先登录", request);
    }

    @ExceptionHandler({BizException.class, GatewayException.class})
    public void handleKnown(
            RuntimeException exception,
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        int status = exception instanceof BizException biz ? biz.status() : ((GatewayException) exception).status();
        writeError(response, status, exception.getMessage(), request);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public void handleValidation(
            MethodArgumentNotValidException exception,
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getDefaultMessage() == null ? "请求参数无效" : error.getDefaultMessage())
                .orElse("请求参数无效");
        writeError(response, 400, message, request);
    }

    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    public void handleNotAcceptable(
            HttpMediaTypeNotAcceptableException exception,
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        writeError(response, 406, "请求的响应格式不受支持", request);
    }

    @ExceptionHandler(Exception.class)
    public void handleUnexpected(
            Exception exception,
            HttpServletRequest request,
            HttpServletResponse response
    ) throws IOException {
        writeError(response, 500, "服务暂时不可用", request);
    }

    private void writeError(
            HttpServletResponse response,
            int status,
            String message,
            HttpServletRequest request
    ) throws IOException {
        if (response.isCommitted()) {
            return;
        }
        String traceId = request.getHeader("X-Request-Id");
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString();
        }
        response.setStatus(status);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        objectMapper.writeValue(response.getOutputStream(), new ApiError(status, message, traceId, Instant.now()));
    }
}
