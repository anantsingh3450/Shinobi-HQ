document.addEventListener('DOMContentLoaded', () => {
    // API endpoints
    const ACCOUNT_ID = 'main'; // Adjust as needed
    const API_BASE = '/api/v1';
    
    // DOM Elements
    const activeTradesTable = document.querySelector('#table-active-trades tbody');
    const previousTradesTable = document.querySelector('#table-previous-trades tbody');
    const countActiveTrades = document.getElementById('count-active-trades');
    
    const valEstimatedTax = document.getElementById('val-estimated-tax');
    const valTotalCharges = document.getElementById('val-total-charges');
    const valNetProfit = document.getElementById('val-net-profit');
    const taxForecastMsg = document.getElementById('tax-forecast-msg');
    
    const btnOpenLogin = document.getElementById('btn-open-login');
    const btnUpdateToken = document.getElementById('btn-update-token');
    const tokenUrlInput = document.getElementById('token-url-input');
    const authStatusMessage = document.getElementById('auth-status-message');

    // Utility to format currency
    const formatCurrency = (val) => {
        return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(val);
    };

    const formatDate = (isoString) => {
        const d = new Date(isoString);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    // Render Active Trades
    const renderActiveTrades = async () => {
        try {
            const res = await fetch(`${API_BASE}/portfolio/${ACCOUNT_ID}/positions/open`);
            const data = await res.json();
            
            if (data.length === 0) {
                activeTradesTable.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">No active positions.</td></tr>`;
                countActiveTrades.textContent = '0';
                return;
            }
            
            countActiveTrades.textContent = data.length;
            activeTradesTable.innerHTML = data.map(pos => {
                const dirClass = pos.direction === 'LONG' ? 'dir-long' : 'dir-short';
                const pnlClass = pos.unrealized_pnl >= 0 ? 'success' : 'danger';
                return `
                    <tr>
                        <td><strong>${pos.market}</strong></td>
                        <td><span class="${dirClass}">${pos.direction}</span></td>
                        <td>${pos.quantity}</td>
                        <td>${formatCurrency(pos.entry_price)}</td>
                        <td class="${pnlClass}">${formatCurrency(pos.unrealized_pnl)}</td>
                    </tr>
                `;
            }).join('');
            
        } catch (err) {
            console.error('Error fetching active trades:', err);
            activeTradesTable.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">Error loading data.</td></tr>`;
        }
    };

    // Render Previous Trades (Trade History)
    const renderPreviousTrades = async () => {
        try {
            const res = await fetch(`${API_BASE}/portfolio/${ACCOUNT_ID}/trades?limit=50`);
            const data = await res.json();
            
            if (data.length === 0) {
                previousTradesTable.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No trade history available.</td></tr>`;
                return;
            }
            
            previousTradesTable.innerHTML = data.map(trade => {
                const dirClass = trade.direction === 'LONG' ? 'dir-long' : 'dir-short';
                // Find PnL if available, else show N/A
                const pnlStr = trade.realized_pnl !== undefined ? formatCurrency(trade.realized_pnl) : '-';
                const pnlClass = trade.realized_pnl >= 0 ? 'success' : (trade.realized_pnl < 0 ? 'danger' : '');
                
                return `
                    <tr>
                        <td>${formatDate(trade.executed_at)}</td>
                        <td><strong>${trade.market}</strong></td>
                        <td><span class="${dirClass}">${trade.direction}</span></td>
                        <td>${trade.status}</td>
                        <td>${formatCurrency(trade.entry_price)}</td>
                        <td class="${pnlClass}">${pnlStr}</td>
                    </tr>
                `;
            }).join('');
            
        } catch (err) {
            console.error('Error fetching trade history:', err);
            previousTradesTable.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">Error loading data.</td></tr>`;
        }
    };

    // Render Tax Info
    const renderTaxInfo = async () => {
        try {
            const res = await fetch(`${API_BASE}/portfolio/${ACCOUNT_ID}/tax`);
            if (res.ok) {
                const data = await res.json();
                valEstimatedTax.textContent = formatCurrency(data.estimated_tax || 0);
                valTotalCharges.textContent = formatCurrency(data.total_charges || 0);
                valNetProfit.textContent = formatCurrency(data.net_profit_after_tax || 0);
                
                if (data.net_profit_after_tax < 0) {
                    valNetProfit.className = 'value danger';
                } else {
                    valNetProfit.className = 'value success';
                }
                
                taxForecastMsg.textContent = data.tax_forecast || "";
            }
        } catch (err) {
            console.error('Error fetching tax info:', err);
        }
    };

    // Handle Manual Login
    btnOpenLogin.addEventListener('click', async () => {
        try {
            const res = await fetch(`${API_BASE}/login/url`);
            if (res.ok) {
                const data = await res.json();
                if (data.url) {
                    window.open(data.url, '_blank');
                    showAuthMessage('Login page opened. Please copy the URL after you are redirected.', 'success');
                }
            } else {
                showAuthMessage('Failed to fetch login URL.', 'error');
            }
        } catch (err) {
            showAuthMessage('Error connecting to server.', 'error');
        }
    });

    btnUpdateToken.addEventListener('click', async () => {
        const tokenUrl = tokenUrlInput.value.trim();
        if (!tokenUrl) {
            showAuthMessage('Please paste the redirect URL.', 'error');
            return;
        }

        const originalBtnText = btnUpdateToken.innerHTML;
        btnUpdateToken.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Updating...';
        btnUpdateToken.disabled = true;

        try {
            const res = await fetch(`${API_BASE}/login/token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token_url: tokenUrl })
            });
            
            const data = await res.json();
            
            if (res.ok && data.success) {
                showAuthMessage('Token updated successfully! Session is active.', 'success');
                tokenUrlInput.value = '';
            } else {
                showAuthMessage(data.error || 'Failed to update token.', 'error');
            }
        } catch (err) {
            showAuthMessage('Error connecting to server.', 'error');
        } finally {
            btnUpdateToken.innerHTML = originalBtnText;
            btnUpdateToken.disabled = false;
        }
    });

    function showAuthMessage(msg, type) {
        authStatusMessage.textContent = msg;
        authStatusMessage.className = `status-message mt-3 ${type === 'success' ? 'success-msg' : 'error-msg'}`;
        authStatusMessage.classList.remove('hidden');
    }

    // Initialization
    const init = () => {
        renderActiveTrades();
        renderPreviousTrades();
        renderTaxInfo();
        
        // Refresh every 10 seconds
        setInterval(() => {
            renderActiveTrades();
            renderPreviousTrades();
            renderTaxInfo();
        }, 10000);
    };

    init();
});
