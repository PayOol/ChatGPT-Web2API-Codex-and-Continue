// Extracted from Continue 2.0.0, Apache-2.0, Continue Dev Inc.
function fromChatCompletionChunk(chunk) {
  const delta = chunk.choices?.[0]?.delta;
  if (delta?.content) {
    return {
      role: "assistant",
      content: delta.content
    };
  } else if (delta?.tool_calls) {
    const toolCalls = delta?.tool_calls.filter((tool_call) => !tool_call.type || tool_call.type === "function").map((tool_call) => ({
      id: tool_call.id,
      type: "function",
      function: {
        name: tool_call.function?.name,
        arguments: tool_call.function?.arguments
      }
    }));
    if (toolCalls.length > 0) {
      return {
        role: "assistant",
        content: "",
        toolCalls
      };
    }
  } else if (delta?.reasoning_content || delta?.reasoning || delta?.reasoning_details?.length) {
    const message = {
      role: "thinking",
      content: delta.reasoning_content || delta.reasoning || "",
      signature: delta?.reasoning_details?.[0]?.signature,
      reasoning_details: delta?.reasoning_details
    };
    return message;
  }
  return void 0;
}
function handleTextDeltaEvent() {}
