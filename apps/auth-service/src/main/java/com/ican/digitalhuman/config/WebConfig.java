package com.ican.digitalhuman.config;

import cn.dev33.satoken.interceptor.SaInterceptor;
import cn.dev33.satoken.router.SaRouter;
import cn.dev33.satoken.stp.StpUtil;
import java.util.List;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final CorsProperties corsProperties;

    public WebConfig(CorsProperties corsProperties) {
        this.corsProperties = corsProperties;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new SaInterceptor(handler -> SaRouter.match("/api/**")
                .notMatch("/api/auth/**")
                .notMatch("/api/health")
                .notMatch("/error")
                .notMatchMethod("OPTIONS")
                .check(r -> StpUtil.checkLogin())));
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        List<String> origins = corsProperties.origins();
        registry.addMapping("/api/**")
                .allowedOriginPatterns(origins.toArray(String[]::new))
                .allowedMethods("GET", "POST", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .exposedHeaders("Content-Type", "Cache-Control")
                .allowCredentials(true)
                .maxAge(3600);
    }
}
