/**
 * NextAura Orchestrator Dashboard - Client JavaScript
 * Handles DAG visualization, real-time SSE updates, task management, and all dashboard interactions
 */

// ==================== State ====================
let sseConnection = null;
let dagData = null;
let tasksData = [];
let metricsData = null;
let logsData = [];
let autoScrollEnabled = true;
let currentFilter = 'all';

// ==================== Initialization ====================
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Dashboard] Initializing...');
    initializeSSE();
    loadInitialData();
    setupEventListeners();
    startTimeDisplay();
});

// ==================== Server-Sent Events ====================
function initializeSSE() {
    if (sseConnection) {
        sseConnection.close();
    }

    sseConnection = new EventSource('/events');

    sseConnection.addEventListener('metrics', (event) => {
        const data = JSON.parse(event.data);
        updateMetrics(data.data);
    });

    sseConnection.addEventListener('dag', (event) => {
        const data = JSON.parse(event.data);
        updateDAG(data);
    });

    sseConnection.addEventListener('tasks', (event) => {
        const data = JSON.parse(event.data);
        updateTasks(data);
    });

    sseConnection.onerror = (error) => {
        console.error('[SSE] Connection error:', error);
        showNotification('Connection lost. Reconnecting...', 'warn');
    };

    sseConnection.onopen = () => {
        console.log('[SSE] Connection established');
    };
}

// ==================== Initial Data Loading ====================
async function loadInitialData() {
    try {
        await Promise.all([
            fetchDAG(),
            fetchTasks(),
            fetchMetrics(),
            fetchLogs(),
        ]);
        renderDAG();
        renderTasks();
        renderLogs();
    } catch (error) {
        console.error('[Dashboard] Failed to load initial data:', error);
        showError('Failed to load dashboard data');
    }
}

async function fetchDAG() {
    const response = await fetch('/api/dag');
    dagData = await response.json();
}

async function fetchTasks() {
    const response = await fetch('/api/tasks');
    tasksData = await response.json();
}

async function fetchMetrics() {
    const response = await fetch('/api/metrics');
    metricsData = await response.json();
    updateMetrics(metricsData);
}

async function fetchLogs() {
    const response = await fetch('/api/logs?limit=50');
    logsData = await response.json();
}

// ==================== DAG Visualization ====================
function renderDAG() {
    const container = document.getElementById('dag-container');
    if (!container || !dagData) return;

    const nodes = dagData.nodes || [];
    const edges = dagData.edges || [];

    // Calculate layout
    const nodeWidth = 200;
    const nodeHeight = 100;
    const horizontalGap = 50;
    const verticalGap = 80;

    // Simple layered layout based on dependencies
    const layers = calculateLayers(nodes, edges);
    
    // Calculate container size
    const maxLayerNodes = Math.max(...layers.map(l => l.length));
    const containerWidth = maxLayerNodes * (nodeWidth + horizontalGap) + horizontalGap;
    const containerHeight = layers.length * (nodeHeight + verticalGap) + verticalGap;

    container.style.width = `${Math.max(containerWidth, 800)}px`;
    container.style.height = `${Math.max(containerHeight, 350)}px`;

    // Clear container
    container.innerHTML = '';

    // Render edges first (behind nodes)
    edges.forEach((edge, index) => {
        const fromNode = nodes.find(n => n.id === edge.from);
        const toNode = nodes.find(n => n.id === edge.to);
        if (fromNode && toNode) {
            renderEdge(container, fromNode, toNode, edge);
        }
    });

    // Render nodes
    nodes.forEach((node, index) => {
        renderNode(container, node, index, layers, nodeWidth, horizontalGap, verticalGap);
    });

    // Update progress
    updateDAGProgress();
}

function calculateLayers(nodes, edges) {
    const layers = [];
    const nodeLayer = {};
    
    // Find nodes with no dependencies (layer 0)
    nodes.forEach(node => {
        if (!node.dependencies || node.dependencies.length === 0) {
            nodeLayer[node.id] = 0;
        }
    });

    // Assign layers based on dependencies
    let changed = true;
    while (changed) {
        changed = false;
        nodes.forEach(node => {
            if (nodeLayer[node.id] === undefined && node.dependencies) {
                const depLayers = node.dependencies.map(depId => nodeLayer[depId]).filter(l => l !== undefined);
                if (depLayers.length === node.dependencies.length) {
                    nodeLayer[node.id] = Math.max(...depLayers) + 1;
                    changed = true;
                }
            }
        });
    }

    // Handle any remaining nodes (circular dependencies or orphaned)
    nodes.forEach(node => {
        if (nodeLayer[node.id] === undefined) {
            nodeLayer[node.id] = 0;
        }
    });

    // Group nodes by layer
    const maxLayer = Math.max(...Object.values(nodeLayer));
    for (let i = 0; i <= maxLayer; i++) {
        layers[i] = nodes.filter(n => nodeLayer[n.id] === i);
    }

    return layers;
}

function renderNode(container, node, index, layers, nodeWidth, horizontalGap, verticalGap) {
    const layerIndex = layers.findIndex(l => l.includes(node));
    const positionInLayer = layers[layerIndex].indexOf(node);
    
    const left = horizontalGap + positionInLayer * (nodeWidth + horizontalGap);
    const top = verticalGap + layerIndex * (nodeHeight + verticalGap);

    const nodeEl = document.createElement('div');
    nodeEl.className = `dag-node status-${node.status}`;
    nodeEl.style.left = `${left}px`;
    nodeEl.style.top = `${top}px`;
    nodeEl.innerHTML = `
        <div class="dag-node-label">${node.label}</div>
        <div class="dag-node-description">${node.description}</div>
    `;
    
    nodeEl.addEventListener('click', () => showNodeDetails(node));
    container.appendChild(nodeEl);
}

function renderEdge(container, fromNode, toNode, edge) {
    // Simple straight line for now
    const edgeEl = document.createElement('div');
    edgeEl.className = `dag-edge ${fromNode.status === 'green' && toNode.status === 'green' ? 'connected' : ''}`;
    
    // Calculate positions (simplified)
    edgeEl.style.width = '100px';
    edgeEl.style.left = '150px';
    edgeEl.style.top = '50px';
    
    container.appendChild(edgeEl);
}

function updateDAG(newDagData) {
    dagData = newDagData;
    renderDAG();
}

function updateDAGProgress() {
    if (!dagData) return;
    
    const nodes = dagData.nodes || [];
    const total = nodes.length;
    const green = nodes.filter(n => n.status === 'green').length;
    const progress = total > 0 ? Math.round((green / total) * 100) : 0;

    const progressEl = document.getElementById('dag-progress');
    if (progressEl) {
        progressEl.textContent = `${progress}% Complete (${green}/${total})`;
    }

    // Update progress bar
    const progressFill = document.getElementById('progress-fill');
    if (progressFill) {
        progressFill.style.width = `${progress}%`;
    }

    // Update narrative
    updateNarrative(progress, green, total);
}

function updateNarrative(progress, green, total) {
    const summaryText = document.getElementById('summary-text');
    const nextTaskText = document.getElementById('next-task-text');

    if (summaryText) {
        if (progress === 0) {
            summaryText.textContent = 'Initializing orchestration...';
        } else if (progress === 100) {
            summaryText.textContent = `✓ All ${total} tasks completed successfully!`;
        } else {
            summaryText.textContent = `Completed ${green} of ${total} tasks. Orchestrator is making progress...`;
        }
    }

    if (nextTaskText && tasksData.length > 0) {
        const pendingTasks = tasksData.filter(t => t.status === 'pending');
        if (pendingTasks.length > 0) {
            const nextTask = pendingTasks.sort((a, b) => a.priority - b.priority)[0];
            nextTaskText.textContent = nextTask.label;
        } else {
            nextTaskText.textContent = 'All tasks queued for execution';
        }
    }
}

function showNodeDetails(node) {
    console.log('[DAG] Node clicked:', node);
    // Could show a modal with more details
}

// ==================== Task Management ====================
function renderTasks() {
    const container = document.getElementById('task-list');
    if (!container) return;

    let filteredTasks = tasksData;
    if (currentFilter === 'pending') {
        filteredTasks = tasksData.filter(t => t.status === 'pending');
    } else if (currentFilter === 'completed') {
        filteredTasks = tasksData.filter(t => t.status === 'completed');
    }

    if (filteredTasks.length === 0) {
        container.innerHTML = '<div class="task-loading">No tasks to display</div>';
        return;
    }

    container.innerHTML = filteredTasks.map(task => `
        <div class="task-item status-${task.status}">
            <div class="task-status-badge ${task.status}"></div>
            <div class="task-info">
                <div class="task-label">${task.label}</div>
                <div class="task-description">${task.description}</div>
            </div>
            <div class="task-priority">P${task.priority}</div>
        </div>
    `).join('');
}

function updateTasks(newTasksData) {
    tasksData = newTasksData;
    renderTasks();
}

// ==================== Logs Display ====================
function renderLogs() {
    const container = document.getElementById('logs-container');
    if (!container) return;

    if (logsData.length === 0) {
        container.innerHTML = '<div class="log-entry"><span class="log-time">--:--:--</span> <span class="log-level info">INFO</span> <span class="log-message">Waiting for logs...</span></div>';
        return;
    }

    container.innerHTML = logsData.map(log => {
        const level = log.source.includes('error') ? 'error' : 
                      log.source.includes('warn') ? 'warn' : 
                      log.source.includes('debug') ? 'debug' : 'info';
        const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '--:--:--';
        
        return `
            <div class="log-entry">
                <span class="log-time">${time}</span>
                <span class="log-level ${level}">${level.toUpperCase()}</span>
                <span class="log-message">${escapeHtml(log.content || log.message || '')}</span>
            </div>
        `;
    }).join('');

    if (autoScrollEnabled) {
        container.scrollTop = container.scrollHeight;
    }
}

function addLogEntry(entry) {
    logsData.push(entry);
    if (logsData.length > 100) {
        logsData.shift();
    }
    renderLogs();
}

// ==================== Metrics Display ====================
function updateMetrics(data) {
    if (!data) return;
    metricsData = data;

    // Update header stats
    document.getElementById('stat-cycles').textContent = data.cycles || 0;
    
    const taskStatus = data.task_status || {};
    const completed = taskStatus.completed || 0;
    const total = taskStatus.total || 0;
    document.getElementById('stat-tasks').textContent = `${completed}/${total}`;
    
    // Update metrics grid
    const dagProgress = data.dag_progress || {};
    document.getElementById('metric-dag-progress').textContent = `${Math.round(dagProgress.progress || 0)}%`;
    document.getElementById('metric-vector').textContent = data.vector_store_entries || 0;
    document.getElementById('metric-data').textContent = data.training_data_files || 0;
    document.getElementById('metric-models').textContent = data.model_checkpoints || 0;
    document.getElementById('metric-logs').textContent = data.log_files || 0;
    document.getElementById('metric-gpu').textContent = data.gpu_enabled ? 'Yes' : 'No';
    
    if (data.timestamp) {
        document.getElementById('metric-timestamp').textContent = new Date(data.timestamp).toLocaleTimeString();
    }
}

// ==================== Vector Store Stats ====================
function updateVectorStats() {
    if (!metricsData) return;

    document.getElementById('vector-total').textContent = metricsData.vector_store_entries || 0;
    document.getElementById('vector-memory').textContent = metricsData.vector_store_entries || 0; // Simplified
    document.getElementById('vector-retrievals').textContent = '0'; // Would need tracking
    document.getElementById('vector-size').textContent = '0 KB'; // Would need calculation
}

// ==================== Event Listeners ====================
function setupEventListeners() {
    // Filter buttons
    document.getElementById('filter-all')?.addEventListener('click', () => {
        currentFilter = 'all';
        renderTasks();
    });

    document.getElementById('filter-pending')?.addEventListener('click', () => {
        currentFilter = 'pending';
        renderTasks();
    });

    document.getElementById('filter-completed')?.addEventListener('click', () => {
        currentFilter = 'completed';
        renderTasks();
    });

    // Log controls
    document.getElementById('clear-logs')?.addEventListener('click', () => {
        logsData = [];
        renderLogs();
    });

    document.getElementById('auto-scroll')?.addEventListener('click', (e) => {
        autoScrollEnabled = !autoScrollEnabled;
        e.target.toggleAttribute('active');
    });

    // Orchestration controls
    document.getElementById('btn-start')?.addEventListener('click', () => {
        sendControlCommand('start');
    });

    document.getElementById('btn-pause')?.addEventListener('click', () => {
        sendControlCommand('pause');
    });

    document.getElementById('btn-stop')?.addEventListener('click', () => {
        sendControlCommand('stop');
    });

    document.getElementById('btn-dispatch')?.addEventListener('click', () => {
        sendControlCommand('dispatch');
    });

    document.getElementById('btn-refresh')?.addEventListener('click', () => {
        loadInitialData();
    });

    // Modal controls
    document.getElementById('modal-close')?.addEventListener('click', hideError);
    document.getElementById('btn-dismiss')?.addEventListener('click', hideError);
    document.getElementById('btn-retry')?.addEventListener('click', () => {
        hideError();
        loadInitialData();
    });

    // Cycle speed
    document.getElementById('cycle-speed')?.addEventListener('change', (e) => {
        console.log('[Dashboard] Cycle speed changed to:', e.target.value);
    });
}

function sendControlCommand(command) {
    console.log('[Dashboard] Sending command:', command);
    // Would need backend endpoint to handle commands
    showNotification(`Command "${command}" sent`, 'info');
}

// ==================== Time Display ====================
function startTimeDisplay() {
    function updateTime() {
        const now = new Date();
        document.getElementById('stat-time').textContent = now.toLocaleTimeString();
    }
    updateTime();
    setInterval(updateTime, 1000);
}

// ==================== Utility Functions ====================
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showNotification(message, type = 'info') {
    console.log(`[Notification] [${type}] ${message}`);
    // Could implement toast notifications
}

function showError(message) {
    const modal = document.getElementById('error-modal');
    const errorMessage = document.getElementById('error-message');
    
    if (modal && errorMessage) {
        errorMessage.textContent = message;
        modal.classList.add('active');
    }
}

function hideError() {
    const modal = document.getElementById('error-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

// ==================== Auto-refresh ====================
// Refresh metrics every 5 seconds
setInterval(() => {
    fetchMetrics().catch(console.error);
}, 5000);

// Refresh logs every 10 seconds
setInterval(() => {
    fetchLogs().then(renderLogs).catch(console.error);
}, 10000);

console.log('[Dashboard] JavaScript loaded successfully');
