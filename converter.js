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

const processTimestamp = (timestamp) => {
    if (timestamp === null || timestamp === undefined) {
        return null;
    }

    try {
        // If it's already an ISO string, convert to milliseconds
        if (typeof timestamp === 'string' && (timestamp.includes('T') || timestamp.includes('Z'))) {
            return new Date(timestamp).getTime();
        }

        // If it's a Unix timestamp (number)
        if (typeof timestamp === 'number') {
            return timestamp * 1000; // Convert to milliseconds
        }

        // If it's a Date object
        if (timestamp instanceof Date) {
            return timestamp.getTime();
        }
    } catch (e) {
        console.warn(`Could not convert timestamp ${timestamp}:`, e);
        return null;
    }
};

const processClaudeMessage = (message, threadId) => {
    if (!message || typeof message !== 'object') {
        return null;
    }

    const role = message.role || 'unknown';
    const content = message.content || '';
    const createTime = message.created_at;

    if (!message.uuid || !role || !content) {
        return null;
    }

    return {
        id: message.uuid,
        threadId: threadId,
        role: role,
        content: content,
        created_at: processTimestamp(createTime),
        model: null, // Claude format doesn't include model info
        status: 'done'
    };
};

const processOpenAIMessage = (message, threadId) => {
    if (!message || typeof message !== 'object') {
        return null;
    }

    const authorInfo = message.author || {};
    const role = typeof authorInfo === 'object' ? authorInfo.role : 'unknown';
    const contentText = extractTextContent(message.content);
    const createTime = message.create_time;
    const modelSlug = message.metadata?.model_slug;
    const status = message.status || 'unknown';

    if (!message.id || !role || createTime === undefined || !contentText) {
        return null;
    }

    return {
        id: message.id,
        threadId: threadId,
        role: role,
        content: contentText,
        created_at: processTimestamp(createTime),
        model: modelSlug,
        status: status
    };
};

const processConversation = (conversation) => {
    if (!conversation || typeof conversation !== 'object') {
        console.warn("Invalid conversation object");
        return null;
    }

    const threadId = conversation.conversation_id || conversation.id || conversation.uuid;
    if (!threadId) {
        console.warn("Missing conversation ID");
        return null;
    }

    // Determine if this is a Claude or OpenAI format
    const isClaudeFormat = 'chat_messages' in conversation;
    const conversationMessages = [];

    if (isClaudeFormat) {
        // Process Claude format
        const chatMessages = conversation.chat_messages || [];
        console.info(`Processing ${chatMessages.length} Claude messages`);

        for (const msg of chatMessages) {
            const processedMsg = processClaudeMessage(msg, threadId);
            if (processedMsg) {
                conversationMessages.push(processedMsg);
            }
        }
    } else {
        // Process OpenAI format
        const mapping = conversation.mapping || {};
        console.info(`Processing ${Object.keys(mapping).length} OpenAI message nodes`);

        for (const [nodeId, node] of Object.entries(mapping)) {
            if (!node || !node.message) continue;

            const processedMsg = processOpenAIMessage(node.message, threadId);
            if (processedMsg) {
                conversationMessages.push(processedMsg);
            }
        }
    }

    if (conversationMessages.length === 0) {
        console.info(`Thread ${threadId} had no valid messages after filtering`);
        return null;
    }

    // Sort messages by creation time
    conversationMessages.sort((a, b) => {
        const timeA = new Date(a.created_at).getTime();
        const timeB = new Date(b.created_at).getTime();
        return timeA - timeB;
    });

    // Find the last message timestamp
    let lastMessageAt = null;
    for (const msg of conversationMessages) {
        const ts = new Date(msg.created_at).getTime();
        if (ts && (!lastMessageAt || ts > lastMessageAt)) {
            lastMessageAt = ts;
        }
    }

    return {
        thread: {
            id: threadId,
            title: conversation.title || conversation.name || '',
            user_edited_title: false,
            status: 'done',
            model: conversation.default_model_slug,
            created_at: processTimestamp(conversation.create_time || conversation.created_at),
            updated_at: processTimestamp(conversation.update_time || conversation.updated_at),
            last_message_at: lastMessageAt ? new Date(lastMessageAt).toISOString().replace('+00:00', 'Z') : null,
        },
        messages: conversationMessages
    };
};

const convertThreadToBeta = (thread) => {
    const now = Date.now();
    return {
        _creationTime: now,
        _id: thread.id,
        createdAt: processTimestamp(thread.created_at),
        generationStatus: thread.status === 'done' ? 'completed' : thread.status,
        lastMessageAt: processTimestamp(thread.last_message_at),
        model: thread.model,
        pinned: false,
        threadId: thread.id,
        title: thread.title,
        updatedAt: processTimestamp(thread.updated_at),
        userId: "user", // Default value
        visibility: "visible",
        id: thread.id,
        last_message_at: processTimestamp(thread.last_message_at),
        created_at: processTimestamp(thread.created_at),
        updated_at: processTimestamp(thread.updated_at),
        status: thread.status === 'done' ? 'completed' : thread.status,
        user_edited_title: thread.user_edited_title
    };
};

const convertMessageToBeta = (message) => {
    const now = Date.now();
    return {
        _creationTime: now,
        _id: message.id,
        content: message.content,
        created_at: processTimestamp(message.created_at),
        messageId: message.id,
        model: message.model,
        role: message.role,
        status: message.status === 'done' ? 'finished_successfully' : message.status,
        threadId: message.threadId,
        updated_at: now,
        userId: "user", // Default value
        id: message.id
    };
};

const convertFile = async (file) => {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (event) => {
            try {
                const data = JSON.parse(event.target.result);
                
                if (!data.threads || !data.messages) {
                    throw new Error("Invalid production schema format");
                }

                const betaThreads = data.threads.map(convertThreadToBeta);
                const betaMessages = data.messages.map(convertMessageToBeta);

                if (!betaThreads.length || !betaMessages.length) {
                    throw new Error("No valid threads or messages found in the input file");
                }

                // Generate descriptive filename
                const timestamp = new Date().toISOString()
                    .replace(/[-:]/g, '')
                    .replace('T', '_')
                    .replace(/\..+/, '');
                const originalName = file.name.replace(/\.[^/.]+$/, ''); // Remove extension
                const outputFilename = `t3chat_beta_export_${originalName}_${timestamp}.json`;

                resolve({
                    threads: betaThreads,
                    messages: betaMessages,
                    version: "1.0.0",
                    metadata: {
                        filename: outputFilename,
                        threadCount: betaThreads.length,
                        messageCount: betaMessages.length,
                        timestamp
                    }
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

// Export the conversion function
window.convertFile = convertFile; 