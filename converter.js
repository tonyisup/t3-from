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

const isoToUnix = (isoString) => {
    if (!isoString) return null;
    try {
        return new Date(isoString).getTime();
    } catch (e) {
        console.warn(`Could not convert ISO string ${isoString}:`, e);
        return null;
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

const processTimestamp = (timestamp, targetFormat) => {
    if (timestamp === null || timestamp === undefined) {
        return null;
    }

    try {
        // If it's already an ISO string
        if (typeof timestamp === 'string' && (timestamp.includes('T') || timestamp.includes('Z'))) {
            console.log("processing time stamp as string", timestamp);
            return targetFormat === 't3-beta' ? isoToUnix(timestamp) : timestamp;
        }

        // If it's a Unix timestamp (number)
        if (typeof timestamp === 'number') {
            console.log("processing time stamp as number", timestamp);
            return targetFormat === 't3-beta' ? timestamp : unixToIso(timestamp);
        }

        // If it's a Date object
        if (timestamp instanceof Date) {
            console.log("processing time stamp as date", timestamp);
            return targetFormat === 't3-beta' ? timestamp.getTime() : timestamp.toISOString().replace('+00:00', 'Z');
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
        created_at: processTimestamp(createTime, 't3-beta'),
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
        created_at: processTimestamp(createTime, 't3-beta'),
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
            created_at: processTimestamp(conversation.create_time || conversation.created_at, 't3-beta'),
            updated_at: processTimestamp(conversation.update_time || conversation.updated_at, 't3-beta'),
            last_message_at: lastMessageAt ? new Date(lastMessageAt).toISOString().replace('+00:00', 'Z') : null,
        },
        messages: conversationMessages
    };
};

const convertThreadToTarget = (thread, targetFormat) => {
    const now = Date.now();
    const baseThread = {
        id: thread.id || thread.threadId,
        title: thread.title,
        status: thread.status === 'done' ? (targetFormat === 't3-beta' ? 'completed' : 'done') : thread.status,
        model: thread.model,
        created_at: processTimestamp(thread.created_at || thread.createdAt, targetFormat),
        updated_at: processTimestamp(thread.updated_at || thread.updatedAt, targetFormat),
        last_message_at: processTimestamp(thread.last_message_at || thread.lastMessageAt, targetFormat),
        user_edited_title: thread.user_edited_title || false
    };

    if (targetFormat === 't3-beta') {
        return {
            ...baseThread,
            _creationTime: now,
            _id: baseThread.id,
            createdAt: processTimestamp(baseThread.created_at, targetFormat),
            generationStatus: baseThread.status,
            lastMessageAt: processTimestamp(baseThread.last_message_at, targetFormat),
            pinned: false,
            threadId: baseThread.id,
            updatedAt: processTimestamp(baseThread.updated_at, targetFormat),
            userId: "user",
            visibility: "visible",
            id: baseThread.id,
            last_message_at: processTimestamp(baseThread.last_message_at, targetFormat),
            created_at: processTimestamp(baseThread.created_at, targetFormat),
            updated_at: processTimestamp(baseThread.updated_at, targetFormat),
            status: baseThread.status
        };
    }

    return baseThread;
};

const convertMessageToTarget = (message, targetFormat) => {
    const now = Date.now();
    const baseMessage = {
        id: message.id || message.messageId,
        threadId: message.threadId,
        role: message.role,
        content: message.content,
        created_at: processTimestamp(message.created_at || message.createdAt, targetFormat),
        model: message.model,
        status: message.status === 'done' ? (targetFormat === 't3-beta' ? 'finished_successfully' : 'done') : message.status
    };

    if (targetFormat === 't3-beta') {
        return {
            ...baseMessage,
            _creationTime: now,
            _id: baseMessage.id,
            messageId: baseMessage.id,
            updated_at: now,
            userId: "user"
        };
    }

    return baseMessage;
};

const detectSourceFormat = (data) => {
    if (!data || typeof data !== 'object') {
        throw new Error("Invalid input data");
    }

    // Check for T3 format
    if (Array.isArray(data.threads) && Array.isArray(data.messages)) {
        return 't3-prod';
    }

    // Check if it's an array of conversations
    const conversations = Array.isArray(data) ? data : (data.conversations || []);
    if (conversations.length === 0) {
        throw new Error("No conversations found in input file");
    }

    // Check first conversation to determine format
    const firstConversation = conversations[0];
    
    // Check for Claude format
    if ('chat_messages' in firstConversation) {
        return 'claude';
    }
    
    // Check for OpenAI format
    if ('mapping' in firstConversation) {
        return 'openai';
    }

    throw new Error("Could not detect source format");
};

const convertFile = async (file, sourceFormat, targetFormat) => {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (event) => {
            try {
                const data = JSON.parse(event.target.result);
                let threads = [];
                let messages = [];

                // Auto-detect source format if not provided
                const detectedFormat = sourceFormat || detectSourceFormat(data);
                console.log(`Detected source format: ${detectedFormat}`);

                // Handle different source formats
                if (detectedFormat === 'openai' || detectedFormat === 'claude') {
                    const conversations = Array.isArray(data) ? data : (data.conversations || []);
                    if (!conversations.length) {
                        throw new Error("No conversations found in input file");
                    }

                    for (const conversation of conversations) {
                        const result = processConversation(conversation);
                        if (result) {
                            threads.push(result.thread);
                            messages.push(...result.messages);
                        }
                    }
                } else if (detectedFormat === 't3-prod' || detectedFormat === 't3-beta') {
                    if (!data.threads || !data.messages) {
                        throw new Error("Invalid T3 schema format");
                    }
                    threads = data.threads;
                    messages = data.messages;
                }

                if (!threads.length || !messages.length) {
                    throw new Error("No valid threads or messages found in the input file");
                }

                // Convert to target format
                const convertedThreads = threads.map(thread => convertThreadToTarget(thread, targetFormat));
                const convertedMessages = messages.map(message => convertMessageToTarget(message, targetFormat));

                // Generate descriptive filename
                const timestamp = new Date().toISOString()
                    .replace(/[-:]/g, '')
                    .replace('T', '_')
                    .replace(/\..+/, '');
                const originalName = file.name.replace(/\.[^/.]+$/, '');
                const outputFilename = `t3chat_${targetFormat}_export_${originalName}_${timestamp}.json`;

                resolve({
                    threads: convertedThreads,
                    messages: convertedMessages,
                    version: targetFormat === 't3-beta' ? "1.0.0" : undefined,
                    metadata: {
                        filename: outputFilename,
                        sourceFormat,
                        targetFormat,
                        threadCount: convertedThreads.length,
                        messageCount: convertedMessages.length,
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