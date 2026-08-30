package com.ican.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ican.digitalhuman.auth.AuthService;
import com.ican.digitalhuman.auth.UserAccount;
import java.io.ByteArrayOutputStream;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

class AgentProxyControllerTest {

    @Test
    void chatStreamDeclaresSseRepresentationAndDelegatesToGateway() throws Exception {
        AuthService authService = mock(AuthService.class);
        AgentGatewayClient gatewayClient = mock(AgentGatewayClient.class);
        UserAccount account = new UserAccount("u-demo", "demo", "演示用户", "user", null);
        when(authService.requireCurrentUser()).thenReturn(account);

        ObjectNode body = new ObjectMapper().createObjectNode().put("message", "hello");
        AgentProxyController controller = new AgentProxyController(authService, gatewayClient);
        ResponseEntity<StreamingResponseBody> response = controller.chatStream(body);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getContentType()).isEqualTo(MediaType.TEXT_EVENT_STREAM);

        ByteArrayOutputStream output = new ByteArrayOutputStream();
        response.getBody().writeTo(output);
        verify(gatewayClient).stream("/internal/chat/stream", body, "u-demo", "demo", output);
    }
}
