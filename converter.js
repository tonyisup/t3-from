// Utility functions for conversion
const unixToIso = (unixTimestamp) => {
    if (unixTimestamp === null || unixTimestamp === undefined) {
        return null;
    }
    try {
        const dt = new Date(unixTimestamp * 1000);
        return dt.toISOString().replace('+00:00', 'Z');
    } catch (e) {
        console.warn(`Could not convert timestamp ${unixTimestamp}:`, e);
        return new Date(0).toISOString().replace('+00:00', 'Z');
    }
};

const extractTextContent = (contentObj) => {
    if (!contentObj || !contentObj.parts || !Array.isArray(contentObj.parts)) {
        return "";
    }
    
    const textParts = contentObj.parts.map(part => {
        if (typeof part === 'string') {
            return part;
        }
        if (part && part.content_type === "text") {
            return part.text || "";
        }
        return "";
    });

    return textParts.filter(p => p).join("\n").trim();
};

const processConversation = (conversation) => {
    if (!conversation || typeof conversation !== 'object') {
        console.warn("Invalid conversation object");
        return null;
    }

    const threadId = conversation.conversation_id || conversation.id;
    if (!threadId) {
        console.warn("Missing conversation ID");
        return null;
    }

    const conversationMessages = [];
    const mapping = conversation.mapping || {};

    for (const [nodeId, node] of Object.entries(mapping)) {
        if (!node || !node.message) continue;

        const message = node.message;
        if (typeof message !== 'object') {
            console.warn(`Invalid message structure in node ${nodeId}`);
            continue;
        }

        const msgId = message.id;
        const authorInfo = message.author || {};
        const role = typeof authorInfo === 'object' ? authorInfo.role : 'unknown';
        const contentText = extractTextContent(message.content);
        const createTime = message.create_time;
        const modelSlug = message.metadata?.model_slug;
        const status = message.status || 'unknown';

        if (!msgId || !role || createTime === undefined || !contentText) {
            continue;
        }

        conversationMessages.push({
            id: msgId,
            threadId: threadId,
            role: role,
            content: contentText,
            created_at: createTime,
            model: modelSlug,
            status: status,
        });
    }

    if (conversationMessages.length === 0) {
        console.info(`Thread ${threadId} had no valid messages after filtering`);
        return null;
    }

    // Sort messages by creation time
    conversationMessages.sort((a, b) => a.created_at - b.created_at);

    // Convert timestamps to ISO format
    let lastMessageAtTs = null;
    for (const msg of conversationMessages) {
        const ts = msg.created_at;
        msg.created_at = unixToIso(ts);
        if (ts !== null && (lastMessageAtTs === null || ts > lastMessageAtTs)) {
            lastMessageAtTs = ts;
        }
    }

    return {
        thread: {
            id: threadId,
            title: conversation.title || '',
            user_edited_title: false,
            status: 'done',
            model: conversation.default_model_slug,
            created_at: unixToIso(conversation.create_time),
            updated_at: unixToIso(conversation.update_time),
            last_message_at: unixToIso(lastMessageAtTs),
        },
        messages: conversationMessages
    };
};

const convertFile = async (file) => {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (event) => {
            try {
                const conversations = JSON.parse(event.target.result);
                if (!Array.isArray(conversations)) {
                    throw new Error("Invalid file format: expected an array of conversations");
                }

                const allThreads = [];
                const allMessages = [];
                const processedIds = new Set();

                for (const conversation of conversations) {
                    const result = processConversation(conversation);
                    if (result) {
                        if (!processedIds.has(result.thread.id)) {
                            allThreads.push(result.thread);
                            processedIds.add(result.thread.id);
                        }
                        allMessages.push(...result.messages);
                    }
                }

                resolve({
                    threads: allThreads,
                    messages: allMessages
                });
            } catch (error) {
                reject(error);
            }
        };

        reader.onerror = () => {
            reject(new Error("Error reading file"));
        };

        reader.readAsText(file);
    });
}; 