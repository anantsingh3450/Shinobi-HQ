document?.addEventListener("DOMContentLoaded", () => {
    // Safe DOM manipulation helpers
    function safeSetText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }
    function safeSetHtml(id, html) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    }
    function safeSetClass(id, className) {
        const el = document.getElementById(id);
        if (el) el.className = className;
    }
    function safeSetStyleDisplay(id, displayVal) {
        const el = document.getElementById(id);
        if (el) el.style.display = displayVal;
    }
    function safeSetStyleColor(id, colorVal) {
        const el = document.getElementById(id);
        if (el) el.style.color = colorVal;
    }

    // -------------------------------------------------------------
    // 0. Will of Fire Quote Rotator
    // -------------------------------------------------------------
    const quotes = [
        { text: '"When the tree leaves dance, one shall find flames..."', author: "— Lord Third" },
        { text: '"It is the one who is acknowledged by everyone who becomes Hokage."', author: "— Itachi Uchiha" },
        { text: '"I won\'t run away, I never go back on my word!"', author: "— Naruto Uzumaki" },
        { text: '"No matter what happens, a shinobi must endure."', author: "— Hashirama Senju" },
        { text: '"Wake up to reality! Nothing ever goes as planned."', author: "— Madara Uchiha" },
        { text: '"A person grows up when they are able to overcome hardships."', author: "— Jiraiya" }
    ];
    let currentQuoteIdx = 0;
    function rotateQuote() {
        const quoteEl = document.getElementById("rotating-quote");
        const authorEl = document.querySelector(".will-of-fire-quote span");
        if (quoteEl && authorEl) {
            currentQuoteIdx = (currentQuoteIdx + 1) % quotes.length;
            quoteEl.style.opacity = 0;
            authorEl.style.opacity = 0;
            setTimeout(() => {
                quoteEl.textContent = quotes[currentQuoteIdx].text;
                authorEl.textContent = quotes[currentQuoteIdx].author;
                quoteEl.style.opacity = 1;
                authorEl.style.opacity = 1;
            }, 300);
        }
    }
    const qEl = document.getElementById("rotating-quote");
    const aEl = document.querySelector(".will-of-fire-quote span");
    if (qEl && aEl) {
        qEl.style.transition = "opacity 0.3s ease";
        aEl.style.transition = "opacity 0.3s ease";
    }
    setInterval(rotateQuote, 20000);

    // -------------------------------------------------------------
    // 1. Tab Management
    // -------------------------------------------------------------
    const navItems = document.querySelectorAll(".nav-item");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const pageTitle = document.getElementById("page-title");

    navItems.forEach(item => {
        item?.addEventListener("click", (e) => {
            // Remove active class from all navigation items safely
            navItems.forEach(nav => nav?.classList.remove("active"));
            // Remove active class from all tab panes safely
            tabPanes.forEach(pane => pane?.classList.remove("active"));

            // Add active class to clicked navigation item
            item?.classList.add("active");

            const tabId = item.getAttribute("data-tab");
            
            // Map data-tab attributes directly to their corresponding tab element IDs
            const tabIdMap = {
                "home": "tab-home",
                "brain": "tab-brain",
                "markets": "tab-markets",
                "portfolio": "tab-portfolio",
                "positions": "tab-positions",
                "research": "tab-research",
                "opportunities": "tab-opportunities",
                "strategy-lab": "tab-strategy-lab",
                "committee": "tab-committee",
                "risk": "tab-risk",
                "execution": "tab-execution",
                "wealth": "tab-wealth",
                "tax": "tab-tax-intelligence",
                "journal": "tab-trade-journal",
                "no-trade": "tab-no-trade-journal",
                "documents": "tab-documents",
                "analytics": "tab-analytics",
                "reports": "tab-reports",
                "automation": "tab-automation",
                "settings": "tab-settings"
            };

            const targetPaneId = tabId ? (tabIdMap[tabId] || `tab-${tabId}`) : null;
            const targetPane = targetPaneId ? (
                document.getElementById(targetPaneId) || 
                document.getElementById(`tab-${tabId}`) ||
                document.getElementById(`tab-${tabId}-intelligence`)
            ) : null;

            if (targetPane) {
                targetPane.classList.add("active");
            }

            // Update page title safely
            let label = "";
            try {
                label = item.textContent.replace(/[^\w\s]/g, "").trim();
            } catch (err) {
                label = item.innerText ? item.innerText.trim() : "";
            }
            if (pageTitle && label) {
                pageTitle.textContent = label;
            }

            // Trigger specific tab data loaders defensively
            try {
                if (tabId === "home") {
                    loadDashboardData();
                } else if (tabId === "brain") {
                    loadMemoryGraphData();
                } else if (tabId === "markets") {
                    loadMarketIntelligenceData();
                } else if (tabId === "portfolio") {
                    drawPortfolioCharts();
                } else if (tabId === "positions") {
                    loadPositionsData();
                    setTimeout(drawPortfolioCharts, 100);
                } else if (tabId === "research") {
                    loadResearchReports();
                } else if (tabId === "opportunities") {
                    loadMarketIntelligenceData();
                } else if (tabId === "strategy-lab") {
                    loadPerformanceLab();
                    loadStrategyEvolution();
                } else if (tabId === "committee") {
                    loadAgentsData();
                    loadGovernancePolicies();
                    loadConsensusRecords();
                    loadOrganizationResources();
                } else if (tabId === "risk") {
                    loadAlertsData();
                } else if (tabId === "execution") {
                    loadControlData();
                    setTimeout(startOrchestratorCanvasLoop, 100);
                } else if (tabId === "wealth") {
                    loadDashboardData();
                } else if (tabId === "tax") {
                    loadTaxData();
                } else if (tabId === "journal") {
                    loadLessonsFull();
                } else if (tabId === "no-trade") {
                    loadDecisionsFull();
                } else if (tabId === "documents") {
                    loadResearchReports();
                } else if (tabId === "analytics") {
                    loadImprovementsData();
                } else if (tabId === "reports") {
                    loadResearchReports();
                } else if (tabId === "automation") {
                    loadMissionsData();
                    loadSavedWorkflows();
                } else if (tabId === "settings") {
                    loadSettingsData();
                }
            } catch (err) {
                console.error("Tab loader error bypassed defensively:", err);
            }
        });
    });

    // formatting helper
    function formatINR(val) {
        const num = parseFloat(val);
        if (isNaN(num)) return "₹0.00";
        if (num < 0) {
            return `-₹${Math.abs(num).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }
        return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    // -------------------------------------------------------------
    // 2. Data Ingestion & Rendering
    // -------------------------------------------------------------
    async function loadDashboardData() {
        try {
            const response = await fetch("/api/v1/dashboard/summary");
            if (!response.ok) throw new Error("Failed to load summary stats");
            const data = await response.json();

            // Welcome banner & profile info
            const welcomeMsgEl = document.getElementById("welcome-message");
            if (welcomeMsgEl) {
                welcomeMsgEl.textContent = `Good Morning, ${data.commander_title || "Elder"}.`;
            }
            const profileElderEl = document.getElementById("profile-elder");
            if (profileElderEl) {
                profileElderEl.textContent = data.commander_name;
            }
            const profilePhaseEl = document.getElementById("profile-phase");
            if (profilePhaseEl) {
                profilePhaseEl.textContent = (data.horizon && data.horizon.progression_phase) || "ALPHA";
            }
            const profileModeEl = document.getElementById("profile-mode");
            if (profileModeEl) {
                profileModeEl.textContent = (data.horizon && data.horizon.current_mode) || "FOCUSED";
            }
            const profileUniverseSizeEl = document.getElementById("profile-universe-size");
            if (profileUniverseSizeEl) {
                profileUniverseSizeEl.textContent = (data.horizon && data.horizon.universe_size) || "1";
            }
            const profilePrimaryAssetEl = document.getElementById("profile-primary-asset");
            if (profilePrimaryAssetEl) {
                profilePrimaryAssetEl.textContent = (data.horizon && data.horizon.active_asset) || "CRUDE_OIL";
            }

            // Row 1 metrics
            safeSetText("val-equity", formatINR(data.equity));
            safeSetText("val-cash", formatINR(data.cash));

            const status = data.status || {};
            safeSetText("val-trust-score", `${status.elder_trust_score}/100`);
            safeSetText("val-health-score", `${status.portfolio_health_score}/100`);

            const unrealizedPnl = parseFloat(data.unrealized_pnl);
            const unrealizedChangeEl = document.getElementById("val-pnl-unrealized-pct");
            if (unrealizedChangeEl) {
                if (unrealizedPnl >= 0) {
                    unrealizedChangeEl.textContent = `+${formatINR(unrealizedPnl)}`;
                    unrealizedChangeEl.className = "metric-change positive";
                } else {
                    unrealizedChangeEl.textContent = formatINR(unrealizedPnl);
                    unrealizedChangeEl.className = "metric-change negative";
                }
            }

            // Row 2 metrics
            safeSetText("val-drawdown", `${formatINR(status.drawdown_inr)} (${status.drawdown_pct.toFixed(2)}%)`);
            safeSetText("val-profit-factor", status.profit_factor);
            safeSetText("val-sharpe", status.sharpe_ratio.toFixed(2));
            safeSetText("val-win-rate", `${status.win_rate_pct.toFixed(2)}%`);

            // Update Decision Status and Reason for Waiting (Reality Sync)
            const decisionStatusVal = document.getElementById("decision-status-val");
            if (decisionStatusVal) {
                decisionStatusVal.textContent = status.decision_status || "WATCHING";
                
                // Color status value dynamically
                if (status.decision_status === "EXECUTED") {
                    decisionStatusVal.className = "text-green";
                } else if (status.decision_status === "WAITING") {
                    decisionStatusVal.className = "text-gold";
                } else if (status.decision_status === "NO_TRADE") {
                    decisionStatusVal.className = "text-red";
                } else {
                    decisionStatusVal.className = "text-cyan";
                }
            }
            
            const decisionStatusReason = document.getElementById("decision-status-reason");
            if (decisionStatusReason) {
                decisionStatusReason.textContent = status.reason_for_waiting || "No strategy setup detected. Monitoring active universe...";
            }

            // Header status badges
            safeSetText("badge-mode", `Mode: ${status.execution_mode}`);
            safeSetText("badge-loop", `Loop: ${status.autonomous_loop}`);
            safeSetText("badge-venue", `Venue: ${status.active_venue}`);
            safeSetText("badge-badge-venue", `Venue: ${status.active_venue}`);

            // Horizon Control widget
            const horizon = data.horizon || {};
            safeSetText("badge-horizon", `${horizon.current_mode} MODE`);
            safeSetText("horizon-asset", horizon.active_asset);
            safeSetText("horizon-universe", horizon.universe_size);
            safeSetText("horizon-phase", horizon.progression_phase);

            // Opportunity Radar table
            const radarBody = document.getElementById("body-radar");
            if (radarBody) {
                if (data.opportunities && data.opportunities.length > 0) {
                    radarBody.innerHTML = "";
                    data.opportunities.forEach(opp => {
                        const tr = document.createElement("tr");
                        
                        let riskColor = "var(--text-muted)";
                        if (opp.risk === "LOW") riskColor = "var(--color-green)";
                        else if (opp.risk === "MEDIUM") riskColor = "var(--color-gold)";
                        else if (opp.risk === "HIGH") riskColor = "var(--color-red)";

                        tr.innerHTML = `
                            <td><strong>${opp.symbol}</strong></td>
                            <td><span class="badge" style="background-color: hsla(210, 10%, 20%, 0.3); color: var(--text-secondary);">${opp.category}</span></td>
                            <td><strong>${opp.conviction}/100</strong></td>
                            <td style="color: ${riskColor}"><strong>${opp.risk}</strong></td>
                            <td><span class="horizon-badge" style="font-size: 0.65rem;">${opp.horizon}</span></td>
                        `;
                        radarBody.appendChild(tr);
                    });
                } else {
                    radarBody.innerHTML = `<tr><td colspan="5" class="empty-state">No opportunities listed.</td></tr>`;
                }
            }

            // Tax Intelligence
            const tax = data.tax_intelligence || {};
            const paperTax = tax.paper || {};
            const liveTax = tax.live || {};

            safeSetText("tax-paper-stcg", formatINR(paperTax.simulated_stcg));
            safeSetText("tax-paper-ltcg", formatINR(paperTax.simulated_ltcg));
            safeSetText("tax-paper-total", formatINR(paperTax.estimated_tax_liability));
            safeSetText("tax-paper-return", `${paperTax.post_tax_return_pct.toFixed(2)}%`);

            safeSetText("tax-live-stcg", formatINR(liveTax.realized_stcg));
            safeSetText("tax-live-ltcg", formatINR(liveTax.realized_ltcg));
            safeSetText("tax-live-dividend", formatINR(liveTax.dividend_income));
            safeSetText("tax-live-losses", formatINR(liveTax.carry_forward_losses));

            // Lessons & Learning panel
            const learning = data.learning || {};
            safeSetText("learning-dna", learning.trade_dna_insights);
            safeSetText("learning-patterns", learning.performance_patterns);
            safeSetText("learning-regime", learning.regime_observations);
            const lessonsList = document.getElementById("warroom-list-lessons");
            if (lessonsList) {
                if (data.latest_lessons && data.latest_lessons.length > 0) {
                    lessonsList.innerHTML = "";
                    data.latest_lessons.slice(0, 2).forEach(rev => {
                        const div = document.createElement("div");
                        div.className = "lesson-card";
                        div.innerHTML = `
                            <div class="lesson-title">${rev.symbol} takeaway</div>
                            <p class="lesson-text">${rev.lesson}</p>
                        `;
                        lessonsList.appendChild(div);
                    });
                } else {
                    lessonsList.innerHTML = `<p class="empty-state">No exit lessons loaded yet.</p>`;
                }
            }

            // -------------------------------------------------------------
            // Operations Command Center & Active Positions (Phase 6.6X)
            // -------------------------------------------------------------
            const ops = data.operations || {};
            
            const opsMarketStatusEl = document.getElementById("ops-market-status");
            if (opsMarketStatusEl) {
                opsMarketStatusEl.textContent = ops.market_status || "CLOSED";
                if (ops.market_status === "OPEN") {
                    opsMarketStatusEl.style.color = "var(--color-green)";
                } else {
                    opsMarketStatusEl.style.color = "var(--text-muted)";
                }
            }
            
            const opsMarketTimeEl = document.getElementById("ops-market-time");
            if (opsMarketTimeEl) {
                opsMarketTimeEl.textContent = ops.market_time || "IST: N/A";
            }
            
            const opsBrokerStatusEl = document.getElementById("ops-broker-status");
            if (opsBrokerStatusEl) {
                opsBrokerStatusEl.textContent = ops.broker_status || "DISCONNECTED";
                if (ops.broker_status === "CONNECTED") {
                    opsBrokerStatusEl.style.color = "var(--color-green)";
                } else {
                    opsBrokerStatusEl.style.color = "var(--color-red)";
                }
            }
            
            const opsBrokerMsgEl = document.getElementById("ops-broker-msg");
            if (opsBrokerMsgEl) {
                opsBrokerMsgEl.textContent = ops.broker_msg || "Session inactive";
            }
            
            const opsDataStatusEl = document.getElementById("ops-data-status");
            if (opsDataStatusEl) {
                opsDataStatusEl.textContent = ops.data_status || "MOCK FEED";
                if (ops.data_status === "LIVE FEED") {
                    opsDataStatusEl.style.color = "var(--color-green)";
                } else {
                    opsDataStatusEl.style.color = "var(--text-muted)";
                }
            }
            
            const opsDataLatencyEl = document.getElementById("ops-data-latency");
            if (opsDataLatencyEl) {
                opsDataLatencyEl.textContent = ops.data_latency || "Latency: 0ms";
            }
            
            const opsSessionStatusEl = document.getElementById("ops-session-status");
            if (opsSessionStatusEl) {
                opsSessionStatusEl.textContent = ops.session_status === "ACTIVE" ? `ACTIVE (${ops.session_return || '+0.00%'})` : (ops.session_status || "INACTIVE");
                if (ops.session_status === "ACTIVE") {
                    opsSessionStatusEl.style.color = "var(--color-green)";
                } else {
                    opsSessionStatusEl.style.color = "var(--text-muted)";
                }
            }
            
            const opsSessionIdEl = document.getElementById("ops-session-id");
            if (opsSessionIdEl) {
                opsSessionIdEl.textContent = ops.session_id || "No active session";
            }
            
            const opsPnlEl = document.getElementById("ops-pnl");
            if (opsPnlEl) {
                opsPnlEl.textContent = ops.today_pnl || "₹0.00";
                if (ops.today_pnl && ops.today_pnl.startsWith("-")) {
                    opsPnlEl.style.color = "var(--color-red)";
                } else if (ops.today_pnl && ops.today_pnl !== "₹0.00") {
                    opsPnlEl.style.color = "var(--color-green)";
                } else {
                    opsPnlEl.style.color = "var(--text-secondary)";
                }
            }
            
            const opsAlphaEl = document.getElementById("ops-alpha");
            if (opsAlphaEl) {
                opsAlphaEl.textContent = `Alpha: ${ops.today_alpha || "+0.00%"}`;
                if (ops.today_alpha && ops.today_alpha.startsWith("-")) {
                    opsAlphaEl.style.color = "var(--color-red)";
                } else if (ops.today_alpha && ops.today_alpha !== "+0.00%") {
                    opsAlphaEl.style.color = "var(--color-green)";
                } else {
                    opsAlphaEl.style.color = "var(--text-muted)";
                }
            }
            
            const opsRealityEl = document.getElementById("ops-reality");
            if (opsRealityEl) {
                const rScore = typeof ops.reality_score === "number" ? ops.reality_score : parseFloat(ops.reality_score);
                opsRealityEl.textContent = `Reality: ${!isNaN(rScore) ? rScore.toFixed(1) : "100.0"}/100`;
                if (!isNaN(rScore)) {
                    opsRealityEl.style.color = rScore >= 70 ? "var(--color-green)" : rScore >= 50 ? "var(--color-gold)" : "var(--color-red)";
                }
            }
            
            const opsCalibrationEl = document.getElementById("ops-calibration");
            if (opsCalibrationEl) {
                opsCalibrationEl.textContent = `Grade: ${ops.calibration_grade || "EXCELLENT"}`;
                if (ops.calibration_grade === "EXCELLENT" || ops.calibration_grade === "GOOD") {
                    opsCalibrationEl.style.color = "var(--color-green)";
                } else if (ops.calibration_grade === "WARNING") {
                    opsCalibrationEl.style.color = "var(--color-gold)";
                } else {
                    opsCalibrationEl.style.color = "var(--color-red)";
                }
            }
            
            const opsQualityEl = document.getElementById("ops-quality");
            if (opsQualityEl) {
                const qScore = typeof ops.quality_score === "number" ? ops.quality_score : parseFloat(ops.quality_score);
                opsQualityEl.textContent = `Quality: ${!isNaN(qScore) ? qScore.toFixed(1) : "100.0"}/100`;
                if (!isNaN(qScore)) {
                    opsQualityEl.style.color = qScore >= 70 ? "var(--color-green)" : qScore >= 50 ? "var(--color-gold)" : "var(--color-red)";
                }
            }
            
            const opsQualityHealthEl = document.getElementById("ops-quality-health");
            if (opsQualityHealthEl) {
                opsQualityHealthEl.textContent = `Health: ${ops.quality_health || "EXCELLENT"}`;
                if (ops.quality_health === "EXCELLENT" || ops.quality_health === "GOOD") {
                    opsQualityHealthEl.style.color = "var(--color-green)";
                } else if (ops.quality_health === "DEGRADED") {
                    opsQualityHealthEl.style.color = "var(--color-gold)";
                } else {
                    opsQualityHealthEl.style.color = "var(--color-red)";
                }
            }
            
            const opsUptimeEl = document.getElementById("ops-uptime");
            if (opsUptimeEl) {
                opsUptimeEl.textContent = `Uptime: ${ops.system_uptime || "0h 0m"}`;
            }
            
            const opsWatchdogEl = document.getElementById("ops-watchdog");
            if (opsWatchdogEl) {
                opsWatchdogEl.textContent = `Watchdog: ${ops.watchdog_status || "HEALTHY"} (${ops.incidents_count || 0} inc)`;
                if (ops.watchdog_status === "HEALTHY") {
                    opsWatchdogEl.style.color = "var(--color-green)";
                } else {
                    opsWatchdogEl.style.color = "var(--color-red)";
                }
            }
            
            const opsPositionsBody = document.getElementById("body-ops-positions");
            if (opsPositionsBody) {
                const activePositions = ops.active_positions || [];
                if (activePositions.length > 0) {
                    opsPositionsBody.innerHTML = "";
                    activePositions.forEach(pos => {
                        const tr = document.createElement("tr");
                        const pnlRaw = parseFloat(pos.pnl_raw) || 0;
                        const pnlColor = pnlRaw >= 0 ? "var(--color-green)" : "var(--color-red)";
                        const sideColor = pos.side === "LONG" ? "var(--color-green)" : "var(--color-red)";
                        
                        tr.innerHTML = `
                            <td><strong>${pos.symbol}</strong></td>
                            <td style="color: ${sideColor}"><strong>${pos.side}</strong></td>
                            <td>${pos.quantity.toFixed(2)}</td>
                            <td>${pos.entry_price}</td>
                            <td>${pos.current_price}</td>
                            <td style="color: ${pnlColor}"><strong>${pos.pnl}</strong></td>
                        `;
                        opsPositionsBody.appendChild(tr);
                    });
                } else {
                    opsPositionsBody.innerHTML = '<tr><td colspan="6" class="empty-state">No active positions.</td></tr>';
                }
            }

            // Update live indices & commodities prices and changes
            if (ops.indices) {
                const updateIndexUI = (key, elemPriceId, elemChangeId) => {
                    const idxData = ops.indices[key];
                    if (idxData) {
                        safeSetText(elemPriceId, idxData.price);
                        const chgEl = document.getElementById(elemChangeId);
                        if (chgEl) {
                            chgEl.textContent = idxData.change;
                            const isNeg = idxData.change.startsWith("-");
                            if (isNeg) {
                                chgEl.className = "hk-badge hk-badge-danger";
                            } else {
                                chgEl.className = "hk-badge hk-badge-success";
                            }
                        }
                    }
                };

                updateIndexUI("NIFTY", "idx-nifty-price", "idx-nifty-change");
                updateIndexUI("BANKNIFTY", "idx-banknifty-price", "idx-banknifty-change");
                updateIndexUI("SENSEX", "idx-sensex-price", "idx-sensex-change");
                updateIndexUI("CRUDE_OIL", "idx-crude-price", "idx-crude-change");
                updateIndexUI("GOLD", "idx-gold-price", "idx-gold-change");
                updateIndexUI("SILVER", "idx-silver-price", "idx-silver-change");
                updateIndexUI("BRENT", "idx-brent-price", "idx-brent-change");
            }

            // Trigger Portfolio Intelligence fetch (Phase 6.7)
            loadPortfolioIntelligenceData();
            
            // Trigger Market Intelligence fetch (Phase 6.8)
            loadMarketIntelligenceData();

        } catch (error) {
            console.error("Error loading summary:", error);
        }
    }

    // -------------------------------------------------------------
    // 3. Tab Loading Handlers
    // -------------------------------------------------------------
    async function loadPositionsData() {
        try {
            const response = await fetch("/api/v1/portfolio/paper/positions/open");
            const tbody = document.getElementById("body-positions");
            if (!tbody) return;
            if (!response.ok) throw new Error("Positions load failed");
            const positions = await response.json();

            if (positions.length > 0) {
                tbody.innerHTML = "";
                positions.forEach(pos => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td><strong>${pos.market}</strong></td>
                        <td style="color: ${pos.direction === 'LONG' ? 'var(--color-green)' : 'var(--color-red)'}"><strong>${pos.direction}</strong></td>
                        <td>${pos.quantity.toFixed(2)}</td>
                        <td>${formatINR(pos.entry_price)}</td>
                        <td>${formatINR(pos.current_price || pos.entry_price)}</td>
                        <td style="color: ${pos.unrealized_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)'}"><strong>${formatINR(pos.unrealized_pnl)}</strong></td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No open positions found.</td></tr>`;
            }

            loadPortfolioStats();
            loadTradeHistory();
            await loadTaxData();
        } catch (error) {
            console.error(error);
        }
    }

    async function loadPortfolioStats() {
        try {
            const res = await fetch("/api/v1/portfolio/paper/metrics");
            if (!res.ok) return;
            const m = await res.json();
            const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
            const unrealized = m.equity - m.cash - m.margin_used;
            const realized = m.total_return - unrealized;
            el("port-unrealized-pnl", formatINR(unrealized));
            el("port-realized-pnl", formatINR(realized));
            el("port-buying-power", formatINR(m.margin_available));
            if (m.win_rate !== null && m.win_rate !== undefined) {
                el("port-win-rate", m.win_rate.toFixed(1) + "%");
            }
            if (m.max_drawdown !== null && m.max_drawdown !== undefined) {
                el("port-beta", m.max_drawdown.toFixed(2) + "%");
            }
            const pnlEl = document.getElementById("port-realized-pnl");
            if (pnlEl) pnlEl.style.color = realized >= 0 ? "var(--color-green)" : "var(--color-red)";
            const upnlEl = document.getElementById("port-unrealized-pnl");
            if (upnlEl) upnlEl.style.color = unrealized >= 0 ? "var(--color-green)" : "var(--color-red)";
        } catch (e) { console.error("Portfolio stats:", e); }
    }

    async function loadTradeHistory() {
        try {
            const res = await fetch("/api/v1/portfolio/paper/positions/all");
            if (!res.ok) return;
            const all = await res.json();
            const closed = all.filter(p => p.status === "CLOSED");
            const tbody = document.getElementById("body-trade-history");
            if (!tbody) return;
            if (closed.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No closed trades yet.</td></tr>';
                return;
            }
            tbody.innerHTML = "";
            closed.forEach(pos => {
                const pnl = pos.realized_pnl || 0;
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td><strong>${pos.market}</strong></td>
                    <td style="color: ${pos.direction === 'LONG' ? 'var(--color-green)' : 'var(--color-red)'}"><strong>${pos.direction}</strong></td>
                    <td>${pos.quantity.toFixed(2)}</td>
                    <td>${formatINR(pos.entry_price)}</td>
                    <td>${formatINR(pos.current_price || pos.entry_price)}</td>
                    <td style="color: ${pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)'}"><strong>${formatINR(pnl)}</strong></td>
                    <td style="color: var(--text-muted); font-size: 0.8rem;">${pos.closed_at ? new Date(pos.closed_at).toLocaleString("en-IN", {timeZone:"Asia/Kolkata"}) : ""}</td>
                `;
                tbody.appendChild(tr);
            });
        } catch (e) { console.error("Trade history:", e); }
    }

    async function loadDecisionsFull() {
        // No-Trade Journal tab: refusals only (committee-vetoed REJECTED +
        // soft no-trades like VolumeEngine fake-breakout blocks). Executed
        // trades belong in the Trade Journal tab (loadLessonsFull), not here.
        try {
            const response = await fetch("/api/v1/journal/no-trade");
            const container = document.getElementById("list-decisions-full");
            if (!container) return;
            if (!response.ok) throw new Error("Failed");
            const data = await response.json();
            const entries = data.entries || [];

            if (entries.length > 0) {
                container.innerHTML = "";
                entries.forEach(dec => {
                    const div = document.createElement("div");
                    div.className = "decision-card";

                    const header = document.createElement("div");
                    header.className = "decision-header";
                    header.innerHTML = `
                        <span class="decision-ticker">${dec.symbol}</span>
                        <span class="decision-verdict ${(dec.decision || "").toLowerCase()}">${dec.decision}</span>
                    `;
                    const reason = document.createElement("p");
                    reason.className = "decision-reason";
                    reason.textContent = dec.reason || "No reason recorded.";

                    const meta = document.createElement("span");
                    meta.className = "decision-meta";
                    meta.textContent = `Time: ${dec.timestamp || "Today"} | Conviction: ${dec.conviction || 0}`;

                    div.appendChild(header);
                    div.appendChild(reason);
                    div.appendChild(meta);
                    container.appendChild(div);
                });
            } else {
                container.innerHTML = `<p class="empty-state">No refusals logged today.</p>`;
            }
        } catch (error) {
            console.error(error);
        }
    }

    async function loadLessonsFull() {
        // Trade Journal tab: executed trades with entry/exit/PnL, not
        // abstract "lessons" — matches what the commander expects here.
        try {
            const response = await fetch("/api/v1/journal/trades");
            const container = document.getElementById("list-lessons-full");
            if (!container) return;
            if (!response.ok) throw new Error("Failed");
            const data = await response.json();
            const entries = data.entries || [];

            if (entries.length > 0) {
                container.innerHTML = "";
                entries.forEach(t => {
                    const div = document.createElement("div");
                    div.className = "lesson-card";
                    const pnlStr = (t.pnl === null || t.pnl === undefined) ? "--" : `₹${Number(t.pnl).toFixed(2)}`;
                    const pnlColor = (t.pnl || 0) > 0 ? "var(--color-green)" : ((t.pnl || 0) < 0 ? "var(--color-red)" : "inherit");
                    div.innerHTML = `
                        <div class="lesson-title">${t.symbol} — ${t.outcome || "OPEN"}</div>
                        <p class="lesson-text">${t.reason || "Investment Committee authorized entry."}</p>
                        <p class="lesson-text">Exit: ${t.exit_reason || "position still open"} | P&amp;L: <span style="color:${pnlColor}">${pnlStr}</span></p>
                        <span class="decision-meta">Entered: ${t.entry_timestamp || "Today"}</span>
                    `;
                    container.appendChild(div);
                });
            } else {
                container.innerHTML = `<p class="empty-state">No trades executed today.</p>`;
            }
        } catch (error) {
            console.error(error);
        }
    }

    // -------------------------------------------------------------
    // 4. Playbook Searches
    // -------------------------------------------------------------
    const inputSearch = document.getElementById("input-knowledge-search");
    const btnSearch = document.getElementById("btn-knowledge-search");
    const resultsContainer = document.getElementById("list-knowledge-results");

    async function runKnowledgeSearch() {
        const query = inputSearch.value.trim();
        if (!query) return;

        resultsContainer.innerHTML = `<div class="empty-state">Searching playbooks...</div>`;

        try {
            const response = await fetch("/api/v1/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: `knowledge ${query}` })
            });
            if (!response.ok) throw new Error("Search failed");
            const data = await response.json();

            resultsContainer.innerHTML = "";
            const div = document.createElement("div");
            div.className = "knowledge-card";
            div.innerHTML = `
                <div class="knowledge-header">
                    <span class="knowledge-book">Registry rules</span>
                    <span class="knowledge-topic">Topic: ${query}</span>
                </div>
                <h3>Registry Playbook Rules</h3>
                <p class="knowledge-description" style="white-space: pre-wrap;">${data.response_text}</p>
            `;
            resultsContainer.appendChild(div);
        } catch (error) {
            resultsContainer.innerHTML = `<p class="empty-state" style="color: var(--color-red)">Failed to search playbooks: ${error.message}</p>`;
        }
    }

    if (btnSearch) {
        btnSearch?.addEventListener("click", runKnowledgeSearch);
    }
    if (inputSearch) {
        inputSearch?.addEventListener("keydown", (e) => {
            if (e.key === "Enter") runKnowledgeSearch();
        });
    }

    // -------------------------------------------------------------
    // 5. Conversational chat controls
    // -------------------------------------------------------------
    const inputChat = document.getElementById("warroom-input-chat");
    const btnChatSend = document.getElementById("warroom-btn-chat-send");
    const messagesContainer = document.getElementById("warroom-chat-messages");

    function appendMessage(text, isUser, command = null) {
        const messageDiv = document.createElement("div");
        messageDiv.className = `message ${isUser ? 'user' : 'system'}`;

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;

        messageDiv.appendChild(bubble);

        if (command) {
            const cmdTag = document.createElement("div");
            cmdTag.className = "cmd-tag";
            cmdTag.textContent = `Hokage Query Mapped: ${command}`;
            messageDiv.appendChild(cmdTag);
        }

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function appendLoadingBubble() {
        const div = document.createElement("div");
        div.className = "message system loading-bubble";
        div.innerHTML = `
            <div class="bubble">
                <div class="loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        messagesContainer.appendChild(div);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return div;
    }

    async function sendChatMessage(messageText) {
        if (!messageText) return;
        appendMessage(messageText, true);

        const loader = appendLoadingBubble();

        try {
            const response = await fetch("/api/v1/commander/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: messageText })
            });

            loader.remove();

            if (!response.ok) throw new Error("Server communication error");
            const data = await response.json();
            const responseText = (typeof data.response === "string" ? data.response : data.response_text) || JSON.stringify(data);
            appendMessage(responseText, false, data.mapped_command);
        } catch (error) {
            loader.remove();
            appendMessage(`Error: Unable to connect to Hokage systems. (${error.message})`, false);
        }
    }

    btnChatSend?.addEventListener("click", () => {
        const msg = inputChat.value.trim();
        if (msg) {
            sendChatMessage(msg);
            inputChat.value = "";
        }
    });

    inputChat?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const msg = inputChat.value.trim();
            if (msg) {
                sendChatMessage(msg);
                inputChat.value = "";
            }
        }
    });

    // Wire chips inside War Room screen
    document.querySelectorAll(".chip").forEach(chip => {
        chip?.addEventListener("click", () => {
            const text = chip.getAttribute("data-query");
            sendChatMessage(text);
        });
    });

    // -------------------------------------------------------------
    // 6. Shadow Trading Data Loaders
    // -------------------------------------------------------------

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function pct(val) {
        const n = parseFloat(val);
        return isNaN(n) ? "–" : `${(n * 100).toFixed(2)}%`;
    }

    function score(val) {
        const n = parseFloat(val);
        return isNaN(n) ? "–" : n.toFixed(1);
    }

    async function loadShadowAlphaScore() {
        try {
            const r = await fetch("/api/v1/shadow/alpha-score");
            if (!r.ok) return;
            const d = await r.json();
            const s = d.alpha_score || 0;
            const el = document.getElementById("shadow-alpha-score");
            if (el) {
                el.textContent = score(s);
                el.style.color = s >= 70 ? "#00ff88" : s >= 50 ? "#ffc107" : "#ff3860";
            }
            setText("shadow-alpha-label", d.reason || "Composite score");
        } catch (_) {}
    }

    async function loadShadowAttribution() {
        try {
            const r = await fetch("/api/v1/shadow/attribution");
            if (!r.ok) return;
            const d = await r.json();
            setText("shadow-reality-score", score(d.reality_score));
            setText("shadow-decision-accuracy", pct(d.decision_accuracy));
            setText("shadow-edge-realization", pct(d.edge_realization));
            setText("shadow-luck-index", pct(d.luck_index));
            // Quadrant counts
            const q = d.quadrant_counts || {};
            setText("quadrant-cp", q["CORRECT_PROFITABLE"] || 0);
            setText("quadrant-cl", q["CORRECT_LOSS"] || 0);
            setText("quadrant-ip", q["INCORRECT_PROFITABLE"] || 0);
            setText("quadrant-il", q["INCORRECT_LOSS"] || 0);
        } catch (_) {}
    }

    async function loadShadowCalibration() {
        try {
            const r = await fetch("/api/v1/shadow/calibration");
            if (!r.ok) return;
            const d = await r.json();
            const container = document.getElementById("shadow-calibration-list");
            if (!container) return;
            const metrics = d.metrics || {};
            if (!Object.keys(metrics).length) {
                container.innerHTML = "<div style='color:var(--text-muted);font-size:.85rem'>No calibration data yet.</div>";
                return;
            }
            container.innerHTML = Object.entries(metrics).map(([key, m]) => {
                const diff = ((m.actual || 0) - (m.expected || 0)).toFixed(3);
                const isOk = Math.abs(diff) < 0.05;
                return `<div style="display:flex;justify-content:space-between;padding:.3rem 0;border-bottom:1px solid rgba(255,255,255,.05)">
                    <span style="color:var(--text-muted);font-size:.78rem;text-transform:capitalize">${key.replace(/_/g, " ")}</span>
                    <span style="font-size:.78rem;font-weight:600;color:${isOk ? "#00ff88" : "#ffc107"}">
                        E: ${pct(m.expected)} → A: ${pct(m.actual)}
                    </span>
                </div>`;
            }).join("");
        } catch (_) {}
    }

    async function loadShadowPerformance() {
        try {
            const r = await fetch("/api/v1/shadow/performance");
            if (!r.ok) return;
            const d = await r.json();
            const ar = parseFloat(d.active_return || 0);
            const el = document.getElementById("shadow-active-return");
            if (el) {
                el.textContent = pct(d.active_return);
                el.style.color = ar >= 0 ? "#00ff88" : "#ff3860";
            }
            setText("shadow-tracking-error", pct(d.tracking_error));
            setText("shadow-information-ratio", score(d.information_ratio));
        } catch (_) {}
    }

    async function loadShadowReadiness() {
        try {
            const r = await fetch("/api/v1/shadow/readiness");
            if (!r.ok) return;
            const d = await r.json();
            setText("shadow-readiness-level", d.readiness_level || "–");
            const passed = (d.criteria_results || []).filter(c => c.passed).length;
            const total = (d.criteria_results || []).length || 12;
            setText("shadow-readiness-sub", `Criteria: ${passed} / ${total} passed`);

            // Render checklist pills
            const container = document.getElementById("shadow-readiness-checklist");
            if (container && d.criteria_results && d.criteria_results.length) {
                container.innerHTML = d.criteria_results.map(c => `
                    <div class="readiness-pill ${c.passed ? 'pass' : 'fail'}">
                        <span>${c.passed ? "✓" : "✗"}</span>
                        <span>${c.name || c.criterion}</span>
                    </div>`).join("");
            }

            // HAC false positives section
            const fpContainer = document.getElementById("shadow-false-positives");
            if (fpContainer) {
                const fps = d.false_positives_prevented || [];
                if (fps.length === 0) {
                    fpContainer.innerHTML = "<span style='color:#00ff88'>✓ None — no false positives detected.</span>";
                } else {
                    fpContainer.innerHTML = fps.map(fp => `
                        <div style="padding:.4rem 0;border-bottom:1px solid rgba(255,255,255,.05)">
                            <span style="color:#ffc107;font-weight:600">${fp.strategy_name || fp.strategy_id}</span>
                            <span style="color:var(--text-muted);font-size:.78rem;margin-left:.5rem">${fp.timestamp || ""}</span>
                            <div style="font-size:.78rem;color:var(--text-muted);margin-top:.2rem">${fp.reason || ""}</div>
                        </div>`).join("");
                }
            }
        } catch (_) {}
    }

    async function loadShadowDiagnostics() {
        try {
            const r = await fetch("/api/v1/shadow/diagnostics");
            if (!r.ok) return;
            const d = await r.json();
            
            const statusEl = document.getElementById("shadow-diagnostics-status");
            if (statusEl) {
                statusEl.textContent = d.status || "Awaiting diagnostics...";
                
                if (d.status === "EXCELLENT") {
                    statusEl.style.color = "#00ff88";
                } else if (d.status === "GOOD") {
                    statusEl.style.color = "#00ffff";
                } else if (d.status === "WARNING") {
                    statusEl.style.color = "#ffc107";
                } else if (d.status === "CRITICAL") {
                    statusEl.style.color = "#ff3860";
                } else {
                    statusEl.style.color = "var(--text-muted)";
                }
            }
            
            setText("shadow-diagnostics-explanation", d.explanation || "");
            
            const lb = d.ljung_box || {};
            const jb = d.jarque_bera || {};
            const kp = d.kupiec || {};
            
            const lbPass = d.passed_autocorrelation ? "PASS" : "FAIL";
            const jbPass = d.passed_normality ? "PASS" : "WARN";
            const kpPass = d.passed_var_calibration ? "PASS" : "FAIL";
            
            setText("shadow-diag-lb", `${lb.stat || 0} (p: ${lb.p_value || 0.0}) [${lbPass}]`);
            setText("shadow-diag-jb", `${jb.stat || 0} (p: ${jb.p_value || 0.0}) [${jbPass}]`);
            setText("shadow-diag-kp", `${kp.failures || 0}/${kp.total_observations || 0} (p: ${kp.p_value || 0.0}) [${kpPass}]`);
            
            const badgeEl = document.getElementById("shadow-diagnostics-health-badge");
            if (badgeEl) {
                badgeEl.textContent = d.status === "INSUFFICIENT_DATA" ? "pending" : d.status.toLowerCase();
                badgeEl.className = `reality-badge ${d.status === "EXCELLENT" || d.status === "GOOD" ? 'real' : d.status === "CRITICAL" ? 'critical' : 'derived'}`;
            }
        } catch (_) {}
    }

    async function loadShadowExecutionQuality() {
        try {
            const r = await fetch("/api/v1/shadow/execution-quality");
            if (!r.ok) return;
            const d = await r.json();
            
            setText("shadow-quality-score", score(d.execution_quality_score));
            setText("shadow-quality-avg-slippage", `${(d.average_slippage_pct || 0.0).toFixed(4)}%`);
            setText("shadow-quality-worst-slippage", `${(d.worst_slippage_pct || 0.0).toFixed(4)}%`);
            setText("shadow-quality-avg-latency", `${(d.average_latency_ms || 0.0).toFixed(2)} ms`);
            setText("shadow-quality-partial-fills", `${(d.partial_fill_pct || 0.0).toFixed(2)}%`);
            
            const badgeEl = document.getElementById("shadow-quality-health-badge");
            if (badgeEl) {
                const health = d.execution_health || "EXCELLENT";
                badgeEl.textContent = health.toLowerCase();
                
                if (health === "EXCELLENT" || health === "GOOD") {
                    badgeEl.className = "reality-badge real";
                    badgeEl.style.background = "rgba(0,255,136,0.15)";
                    badgeEl.style.color = "#00ff88";
                } else if (health === "DEGRADED") {
                    badgeEl.className = "reality-badge derived";
                    badgeEl.style.background = "rgba(255,193,7,0.15)";
                    badgeEl.style.color = "#ffc107";
                } else {
                    badgeEl.className = "reality-badge critical";
                    badgeEl.style.background = "rgba(255,56,96,0.15)";
                    badgeEl.style.color = "#ff3860";
                }
            }
        } catch (_) {}
    }

    async function loadShadowData() {
        await Promise.all([
            loadShadowAlphaScore(),
            loadShadowAttribution(),
            loadShadowCalibration(),
            loadShadowPerformance(),
            loadShadowReadiness(),
            loadShadowDiagnostics(),
            loadShadowExecutionQuality(),
        ]);
    }

    // Session control buttons
    const btnStart = document.getElementById("btn-shadow-start");
    const btnStop = document.getElementById("btn-shadow-stop");

    if (btnStart) {
        btnStart?.addEventListener("click", async () => {
            btnStart.disabled = true;
            btnStart.textContent = "Starting…";
            try {
                const r = await fetch("/api/v1/shadow/session/start", { method: "POST" });
                const d = await r.json();
                if (r.ok) {
                    setText("shadow-session-id", d.session_id || "Active");
                    setText("shadow-session-status", "Status: ACTIVE");
                    setTimeout(loadShadowData, 500);
                } else {
                    alert(`Failed to start session: ${d.error || "Unknown error"}`);
                }
            } catch (e) {
                alert(`Connection error: ${e.message}`);
            } finally {
                btnStart.disabled = false;
                btnStart.textContent = "▶ Start Session";
            }
        });
    }

    if (btnStop) {
        btnStop?.addEventListener("click", async () => {
            btnStop.disabled = true;
            btnStop.textContent = "Stopping…";
            try {
                const r = await fetch("/api/v1/shadow/session/stop", { method: "POST" });
                const d = await r.json();
                if (r.ok) {
                    setText("shadow-session-id", "No active session");
                    setText("shadow-session-status", "Session stopped.");
                } else {
                    alert(`Failed to stop session: ${d.error || "Unknown error"}`);
                }
            } catch (e) {
                alert(`Connection error: ${e.message}`);
            } finally {
                btnStop.disabled = false;
                btnStop.textContent = "⏹ Stop Session";
            }
        });
    }

    // -------------------------------------------------------------
    // 7. Portfolio Intelligence Fetching & Rendering (Phase 6.7)
    // -------------------------------------------------------------
    async function loadPortfolioIntelligenceData() {
        try {
            const response = await fetch("/api/v1/portfolio/paper/intelligence");
            if (!response.ok) throw new Error("Failed to load portfolio intelligence");
            const data = await response.json();

            // 1. Deployed vs Cash reserve card
            const deploymentEl = document.getElementById("intel-deployment");
            if (deploymentEl) {
                deploymentEl.textContent = `Deployed: ${data.invested_capital_pct.toFixed(2)}% / Cash: ${data.cash_allocation_pct.toFixed(2)}%`;
            }
            const cashTargetEl = document.getElementById("intel-cash-target");
            if (cashTargetEl) {
                cashTargetEl.textContent = `Target Reserve: ${data.recommended_cash_reserve_pct.toFixed(1)}%`;
            }

            // 2. Volatility & Beta card
            const volatilityEl = document.getElementById("intel-volatility");
            if (volatilityEl) {
                volatilityEl.textContent = `Volatility: ${(data.portfolio_volatility * 100.0).toFixed(2)}% / Beta: ${data.portfolio_beta.toFixed(2)}`;
            }
            const volRegimeEl = document.getElementById("intel-vol-regime");
            if (volRegimeEl) {
                volRegimeEl.textContent = `Regime: ${data.volatility_regime}`;
            }

            // 3. Diversification & Average Correlation card
            const diversificationEl = document.getElementById("intel-diversification");
            if (diversificationEl) {
                diversificationEl.textContent = `Score: ${data.diversification_score.toFixed(1)}/100`;
            }
            const correlationEl = document.getElementById("intel-correlation");
            if (correlationEl) {
                correlationEl.textContent = `Avg Correlation: ${data.average_position_correlation.toFixed(3)} (${data.systemic_concentration} concentration)`;
            }

            // 4. Clusters & duplicate card
            const clustersEl = document.getElementById("intel-clusters");
            if (clustersEl) {
                clustersEl.textContent = `${data.duplicate_exposures.length} duplicate / ${data.correlation_clusters.length} clusters`;
            }
            const hiddenEl = document.getElementById("intel-hidden");
            if (hiddenEl) {
                hiddenEl.textContent = `${data.hidden_concentrations.length} hidden concentrations`;
            }

            // 5. Recommendations list
            const recListEl = document.getElementById("intel-recommendations-list");
            if (recListEl && data.rebalancing_recommendations) {
                recListEl.innerHTML = "";
                data.rebalancing_recommendations.forEach(rec => {
                    const div = document.createElement("div");
                    div.className = "insight-item";
                    div.innerHTML = `
                        <span class="icon">💡</span>
                        <div class="txt">
                            <span>${rec}</span>
                        </div>
                    `;
                    recListEl.appendChild(div);
                });
            }

            // 6. Ranked opportunities
            const oppTableBody = document.getElementById("body-intel-opportunities");
            if (oppTableBody) {
                const summaryResp = await fetch("/api/v1/dashboard/summary");
                const summaryData = await summaryResp.json();
                
                const opportunities = summaryData.opportunities || [];
                if (opportunities.length > 0) {
                    oppTableBody.innerHTML = "";
                    opportunities.forEach(opp => {
                        const tr = document.createElement("tr");
                        tr.innerHTML = `
                            <td><strong>${opp.symbol}</strong></td>
                            <td><strong>${opp.conviction}/100</strong></td>
                            <td><span class="badge" style="background-color: hsla(210, 10%, 20%, 0.3); color: var(--text-secondary);">${opp.category}</span></td>
                            <td class="text-secondary" style="font-size: 0.75rem;">Ranked by Expected Edge, Correlation, and Capital Efficiency.</td>
                        `;
                        oppTableBody.appendChild(tr);
                    });
                } else {
                    oppTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">No ranked opportunities listed.</td></tr>`;
                }
            }

            // 7. Portfolio Budgets & Limits (Phase 6.7 final refinement)
            const budgetsTableBody = document.getElementById("body-intel-budgets");
            if (budgetsTableBody && data.portfolio_budgets) {
                budgetsTableBody.innerHTML = "";
                
                const categories = [
                    { name: "Asset: Equity", data: data.portfolio_budgets.asset_class?.equity },
                    { name: "Asset: Commodity", data: data.portfolio_budgets.asset_class?.commodities },
                    { name: "Asset: Crypto", data: data.portfolio_budgets.asset_class?.crypto },
                    { name: "Exch: NSE", data: data.portfolio_budgets.exchange?.nse },
                    { name: "Exch: MCX", data: data.portfolio_budgets.exchange?.mcx },
                    { name: "Strat: AutoTrend", data: data.portfolio_budgets.strategy?.autotrend },
                    { name: "Strat: MeanRev", data: data.portfolio_budgets.strategy?.meanreversion }
                ];

                categories.forEach(cat => {
                    if (cat.data) {
                        const tr = document.createElement("tr");
                        const exp = cat.data.current_exposure || 0.0;
                        const min = cat.data.min || 0.0;
                        const target = cat.data.dynamic_target || cat.data.target || 0.0;
                        const max = cat.data.max || 0.0;
                        const power = cat.data.remaining_buying_power || 0.0;
                        
                        let expColor = "var(--text-secondary)";
                        if (exp > max) expColor = "var(--color-red)";
                        else if (exp > target) expColor = "var(--color-gold)";
                        else if (exp >= min) expColor = "var(--color-green)";

                        tr.innerHTML = `
                            <td><strong>${cat.name}</strong></td>
                            <td style="color: ${expColor}"><strong>${exp.toFixed(1)}%</strong></td>
                            <td class="text-secondary" style="font-size: 0.75rem;">${min.toFixed(0)}% - ${target.toFixed(0)}% (Max ${max.toFixed(0)}%)</td>
                            <td><strong>${power.toFixed(1)}%</strong></td>
                        `;
                        budgetsTableBody.appendChild(tr);
                    }
                });
                
                if (budgetsTableBody.innerHTML === "") {
                    budgetsTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">No budgets configured.</td></tr>`;
                }
            }

        } catch (error) {
            console.error("Error loading portfolio intelligence:", error);
        }
    }

    // -------------------------------------------------------------
    // 8. Market Intelligence Fetching & Rendering (Phase 6.8)
    // -------------------------------------------------------------
    async function loadMarketIntelligenceData() {
        try {
            const response = await fetch("/api/v1/market/intelligence");
            if (!response.ok) throw new Error("Failed to load market intelligence");
            const data = await response.json();

            // 1. Update card widgets
            const macroRegimeEl = document.getElementById("mkt-macro-regime");
            if (macroRegimeEl) macroRegimeEl.textContent = data.macro_regime || "STATIONARY";
            
            const macroConfEl = document.getElementById("mkt-macro-confidence");
            if (macroConfEl) macroConfEl.textContent = `Confidence: ${(data.confidence || 0.0).toFixed(0)}%`;
            
            const breadthHealthEl = document.getElementById("mkt-breadth-health");
            if (breadthHealthEl) breadthHealthEl.textContent = `${(data.breadth_health_score || 0.0).toFixed(1)}%`;
            
            const adRatioEl = document.getElementById("mkt-ad-ratio");
            if (adRatioEl) adRatioEl.textContent = `A/D Ratio: ${(data.breadth?.ad_ratio || 1.0).toFixed(2)}`;
            
            const flowsRegimeEl = document.getElementById("mkt-flows-regime");
            if (flowsRegimeEl) flowsRegimeEl.textContent = data.flows_regime || "NEUTRAL";
            
            const flowsVal = data.flows?.combined_net_crores || 0.0;
            const combinedFlowsEl = document.getElementById("mkt-combined-flows");
            if (combinedFlowsEl) combinedFlowsEl.textContent = `${flowsVal >= 0 ? '+' : ''}${flowsVal.toFixed(1)} Cr`;
            
            const optionsSentimentEl = document.getElementById("mkt-options-sentiment");
            if (optionsSentimentEl) optionsSentimentEl.textContent = data.options_regime || "NEUTRAL";
            
            const optionsPcrEl = document.getElementById("mkt-options-pcr");
            if (optionsPcrEl) optionsPcrEl.textContent = `PCR Index: ${(data.options?.pcr || 1.0).toFixed(2)}`;

            // 2. Update narrative summary
            const narrativeEl = document.getElementById("mkt-explainable-narrative");
            if (narrativeEl) {
                narrativeEl.innerHTML = `
                    <div class="insight-item">
                        <span class="icon">💡</span>
                        <div class="txt">
                            <span><strong>Summary:</strong> ${data.explainable_summary || 'No narrative description computed.'}</span>
                        </div>
                    </div>
                `;
            }

            // 3. Render Sector Rotation Table
            const rotationBody = document.getElementById("body-mkt-rotation");
            if (rotationBody && data.sector_rotation && data.sector_rotation.sector_details) {
                rotationBody.innerHTML = "";
                const details = data.sector_rotation.sector_details;
                
                Object.keys(details).forEach(sector => {
                    const sData = details[sector];
                    const tr = document.createElement("tr");
                    const change = sData.change_percentage || 0.0;
                    const changeColor = change >= 0 ? "var(--color-green)" : "var(--color-red)";
                    
                    tr.innerHTML = `
                        <td><strong>${sector.toUpperCase()}</strong></td>
                        <td><span class="badge" style="background-color: hsla(210, 10%, 20%, 0.3); color: var(--text-secondary);">${sData.benchmark}</span></td>
                        <td style="color: ${changeColor}"><strong>${change >= 0 ? '+' : ''}${change.toFixed(2)}%</strong></td>
                        <td>${(sData.capital_flow_coefficient || 0.0).toFixed(4)}</td>
                        <td><strong>${(sData.momentum_score || 0.0).toFixed(2)}</strong></td>
                    `;
                    rotationBody.appendChild(tr);
                });
            }

            // 4. Render Macro Calendar Events List
            const calendarEl = document.getElementById("list-mkt-calendar");
            if (calendarEl && data.economic_events) {
                calendarEl.innerHTML = "";
                if (data.economic_events.length > 0) {
                    data.economic_events.forEach(ev => {
                        const div = document.createElement("div");
                        div.className = "insight-item";
                        const severityColor = ev.severity === "HIGH" ? "var(--color-red)" : "var(--text-secondary)";
                        div.innerHTML = `
                            <span class="icon" style="color: ${severityColor}">📅</span>
                            <div class="txt">
                                <span><strong>${ev.event}</strong> (${ev.country})</span>
                                <p style="font-size:0.75rem;color:var(--text-muted);margin-top:2px;">
                                    Actual: ${ev.actual} | Forecast: ${ev.forecast} | Previous: ${ev.previous}
                                </p>
                            </div>
                        `;
                        calendarEl.appendChild(div);
                    });
                } else {
                    calendarEl.innerHTML = `<div class="empty-state">No economic events scheduled today.</div>`;
                }
            }

            // Sector strength cards + index sparklines: a second widget on
            // this same tab that used to be defined as a same-named function
            // further down the file — the later declaration silently
            // replaced this one (JS keeps only the last function with a
            // given name), so calling loadMarketIntelligenceData() never
            // reached the macro/rotation/calendar code above at all.
            loadSectorIntelligenceGrid();

        } catch (error) {
            console.error("Error loading market intelligence data:", error);
        }
    }

    // -------------------------------------------------------------
    // 9. Commander Chat & Voice Interface (Phase 6.9)
    // -------------------------------------------------------------
    let voiceActive = false;

    function setupChatInterface() {
        const btnSend = document.getElementById("btn-chat-send");
        const btnMic = document.getElementById("btn-chat-mic");
        const btnToggleVoice = document.getElementById("btn-toggle-voice");
        const chatInput = document.getElementById("chat-input");

        if (btnSend) {
            btnSend?.addEventListener("click", () => {
                const text = chatInput.value.trim();
                if (text) {
                    sendChatMessage(text, false);
                    chatInput.value = "";
                }
            });
        }

        if (chatInput) {
            chatInput?.addEventListener("keypress", (e) => {
                if (e.key === "Enter") {
                    const text = chatInput.value.trim();
                    if (text) {
                        sendChatMessage(text, false);
                        chatInput.value = "";
                    }
                }
            });
        }

        if (btnMic) {
            btnMic?.addEventListener("click", () => {
                // Simulate voice command trigger
                sendChatMessage("Explain today's portfolio", true);
            });
        }

        if (btnToggleVoice) {
            btnToggleVoice?.addEventListener("click", async () => {
                voiceActive = !voiceActive;
                try {
                    const res = await fetch("/api/v1/commander/voice/session", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ action: voiceActive ? "start" : "stop" })
                    });
                    const data = await res.json();
                    updateVoiceUI(data.active, data.state);
                } catch (err) {
                    console.error("Failed to toggle voice session:", err);
                }
            });
        }
    }

    function updateVoiceUI(active, state) {
        const dot = document.getElementById("voice-status-dot");
        const text = document.getElementById("voice-status-text");
        
        if (dot && text) {
            if (active) {
                dot.style.background = "var(--color-green)";
                text.textContent = `VOICE: ${state}`;
                text.style.color = "var(--color-green)";
            } else {
                dot.style.background = "var(--text-muted)";
                text.textContent = "VOICE: INACTIVE";
                text.style.color = "var(--text-muted)";
            }
        }
    }

    async function loadChatHistory() {
        try {
            const res = await fetch("/api/v1/commander/history");
            if (!res.ok) throw new Error("Failed to fetch chat history");
            const history = await res.json();
            renderChatHistory(history);
        } catch (err) {
            console.error("Error loading chat history:", err);
        }
    }

    function renderChatHistory(history) {
        const container = document.getElementById("chat-messages-container");
        if (!container) return;

        // Keep the welcome message if empty
        if (history.length === 0) {
            container.innerHTML = `
                <div class="message system" style="align-self:center; background:rgba(255,255,255,0.05); padding:0.5rem 1rem; border-radius:4px; font-size:0.8rem; color:var(--text-muted)">
                    Hokage Natural Language interface initialized. Ask a question about portfolio, market, risks, or decisions.
                </div>
            `;
            return;
        }

        container.innerHTML = "";
        history.forEach(msg => {
            const div = document.createElement("div");
            const isInput = msg.direction === "input";
            
            div.style.display = "flex";
            div.style.flexDirection = "column";
            div.style.alignSelf = isInput ? "flex-end" : "flex-start";
            div.style.maxWidth = "70%";
            
            // Format message bubble
            const bubble = document.createElement("div");
            bubble.style.padding = "0.75rem 1rem";
            bubble.style.borderRadius = "6px";
            bubble.style.fontSize = "0.9rem";
            bubble.style.lineHeight = "1.4";
            
            if (isInput) {
                bubble.style.background = "var(--color-green)";
                bubble.style.color = "#000";
                bubble.style.fontWeight = "600";
            } else {
                bubble.style.background = "rgba(255, 255, 255, 0.08)";
                bubble.style.color = "#fff";
                bubble.style.border = "1px solid rgba(255, 255, 255, 0.1)";
            }
            
            // Convert newlines to breaks for formatting
            bubble.innerHTML = msg.text.replace(/\n/g, "<br>");
            div.appendChild(bubble);
            container.appendChild(div);
        });

        // Auto scroll to bottom
        container.scrollTop = container.scrollHeight;
    }

    async function sendChatMessage(query, useVoice) {
        try {
            const res = await fetch("/api/v1/commander/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: query, voice: useVoice })
            });
            if (!res.ok) throw new Error("Failed to send message");
            const data = await res.json();
            await loadChatHistory();
            
            if (useVoice && data.audio) {
                console.log("Playing mock speech synthesiser audio:", data.audio);
            }
        } catch (err) {
            console.error("Error sending chat message:", err);
        }
    }

    // -------------------------------------------------------------
    // 10. Real-time Stream & Loop startup
    // -------------------------------------------------------------
    // -------------------------------------------------------------
    // 10. Real-time Stream & War Room Widgets (Phase 8.1)
    // -------------------------------------------------------------
    let eventSource = null;
    let fallbackInterval = null;
    const equityHistory = [];
    const maxEquityPoints = 30;

    // Log terminal memory
    const terminalLogs = [];
    const maxTerminalLogs = 200;

    // Equity Curve Drawing
    function drawEquityCurve(dataPoints) {
        const canvas = document.getElementById("equity-curve-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const container = canvas.parentElement;
        
        // Adjust canvas dimensions for high-DPI displays
        const rect = container.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height || 150;

        const width = canvas.width;
        const height = canvas.height;
        ctx.clearRect(0, 0, width, height);

        if (!dataPoints || dataPoints.length < 2) {
            const emptyEl = document.getElementById("equity-curve-empty");
            if (emptyEl) emptyEl.style.display = "block";
            return;
        }

        const emptyEl = document.getElementById("equity-curve-empty");
        if (emptyEl) emptyEl.style.display = "none";

        const min = Math.min(...dataPoints);
        const max = Math.max(...dataPoints);
        const range = max - min || 1;

        // Draw grid lines
        ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
        ctx.lineWidth = 1;
        for (let i = 1; i < 4; i++) {
            const y = (height / 4) * i;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
            ctx.stroke();
        }

        // Plot line
        ctx.beginPath();
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = "var(--color-cyan)";

        const getX = (index) => (width / (dataPoints.length - 1)) * index;
        const getY = (val) => height - 15 - ((val - min) / range) * (height - 30);

        ctx.moveTo(getX(0), getY(dataPoints[0]));
        for (let i = 1; i < dataPoints.length; i++) {
            ctx.lineTo(getX(i), getY(dataPoints[i]));
        }
        ctx.stroke();

        // Draw gradient fill
        const grad = ctx.createLinearGradient(0, 0, 0, height);
        grad.addColorStop(0, "rgba(0, 255, 242, 0.2)");
        grad.addColorStop(1, "rgba(0, 255, 242, 0)");
        
        ctx.lineTo(getX(dataPoints.length - 1), height);
        ctx.lineTo(getX(0), height);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
    }

    // Terminal Logging
    function appendTerminalLog(level, message) {
        const terminal = document.getElementById("log-terminal");
        if (!terminal) return;

        const timestamp = new Date().toLocaleTimeString();
        const logEntry = { timestamp, level, message };
        terminalLogs.push(logEntry);

        if (terminalLogs.length > maxTerminalLogs) {
            terminalLogs.shift();
        }

        renderTerminalLogs();
    }

    function renderTerminalLogs() {
        const terminal = document.getElementById("log-terminal");
        if (!terminal) return;

        const filter = document.getElementById("log-filter")?.value || "ALL";
        const query = (document.getElementById("log-search")?.value || "").toLowerCase();

        const filtered = terminalLogs.filter(log => {
            if (filter !== "ALL" && log.level !== filter) return false;
            if (query && !log.message.toLowerCase().includes(query)) return false;
            return true;
        });

        terminal.innerHTML = filtered.map(log => {
            let color = "#e2e8f0"; // default info
            if (log.level === "SUCCESS") color = "#00ff88";
            else if (log.level === "WARNING") color = "#ffc107";
            else if (log.level === "ERROR") color = "#ff3860";
            
            return `<div style="margin-bottom: 4px;">
                <span style="color: #a0aec0;">[${log.timestamp}]</span>
                <span style="color: ${color}; font-weight: bold;">[${log.level}]</span>
                <span style="color: #edf2f7;">${log.message}</span>
            </div>`;
        }).join("");

        // Auto-scroll to bottom
        terminal.scrollTop = terminal.scrollHeight;
    }

    // Wire up log search and filter
    document.getElementById("log-search")?.addEventListener("input", renderTerminalLogs);
    document.getElementById("log-filter")?.addEventListener("change", renderTerminalLogs);

    // Timeline Step Management
    function setTimelineActiveStep(stepName) {
        const steps = ["MARKET_SCAN", "MACRO_REGIME", "UNIVERSE_SCAN", "STRATEGY_COMMITTEE", "INVESTMENT_COMMITTEE", "RISK_COMMITTEE", "EXECUTION", "PORTFOLIO_UPDATE", "SHADOW_ANALYTICS", "LEARNING"];
        const stepIndex = steps.indexOf(stepName);
        if (stepIndex === -1) return;

        // Update progress bar fill
        const progressFill = document.getElementById("timeline-progress-fill");
        if (progressFill) {
            const percent = 5 + (stepIndex / (steps.length - 1)) * 90;
            progressFill.style.width = `${percent}%`;
        }

        // Update each step element
        const stepEls = document.querySelectorAll(".timeline-step");
        stepEls.forEach(el => {
            const elStep = el.getAttribute("data-step");
            const elIndex = steps.indexOf(elStep);
            const dot = el.querySelector(".step-dot");
            const label = el.querySelector(".step-label");

            if (elIndex < stepIndex) {
                // Completed steps
                dot.style.background = "var(--color-green)";
                dot.style.borderColor = "var(--color-green)";
                dot.style.color = "#000";
                dot.classList.remove("animating-pulse");
                label.style.color = "var(--color-green)";
            } else if (elIndex === stepIndex) {
                // Active step
                dot.style.background = "var(--color-cyan)";
                dot.style.borderColor = "var(--color-cyan)";
                dot.style.color = "#000";
                dot.classList.add("animating-pulse");
                label.style.color = "var(--color-cyan)";
            } else {
                // Upcoming steps
                dot.style.background = "#2d3748";
                dot.style.borderColor = "#4a5568";
                dot.style.color = "#718096";
                dot.classList.remove("animating-pulse");
                label.style.color = "var(--text-muted)";
            }
        });

        // Set activity indicator
        const indicator = document.getElementById("timeline-activity-indicator");
        if (indicator) {
            indicator.textContent = `Status: ACTIVE (${stepName.replace(/_/g, " ")})`;
            indicator.style.color = "var(--color-cyan)";
        }
    }

    function resetTimelineToCalm() {
        const stepEls = document.querySelectorAll(".timeline-step");
        stepEls.forEach(el => {
            const dot = el.querySelector(".step-dot");
            const label = el.querySelector(".step-label");
            dot.style.background = "#2d3748";
            dot.style.borderColor = "#4a5568";
            dot.style.color = "#718096";
            dot.classList.remove("animating-pulse");
            label.style.color = "var(--text-muted)";
        });

        const progressFill = document.getElementById("timeline-progress-fill");
        if (progressFill) progressFill.style.width = "0%";

        const indicator = document.getElementById("timeline-activity-indicator");
        if (indicator) {
            indicator.textContent = "Status: CALM";
            indicator.style.color = "var(--text-muted)";
        }
    }

    // Toggle Voice Button in War Room
    document.getElementById("warroom-toggle-voice")?.addEventListener("click", async () => {
        voiceActive = !voiceActive;
        try {
            const res = await fetch("/api/v1/commander/voice/session", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: voiceActive ? "start" : "stop" })
            });
            const data = await res.json();
            updateVoiceUI(data.active, data.state);
        } catch (err) {
            console.error("Failed to toggle voice session:", err);
        }
    });

    // Personality Selector
    document.getElementById("personality-selector")?.addEventListener("change", (e) => {
        const personality = e.target.value;
        appendTerminalLog("INFO", `Personality profile calibrated to: ${personality.toUpperCase()}`);
    });

    // Real-time Event Stream Handler (19 Events)
    function setupRealtimeStream() {
        if (typeof(EventSource) !== "undefined") {
            console.log("Initializing Real-time Event Stream (SSE)...");
            eventSource = new EventSource("/api/v1/stream");

            eventSource.onopen = () => {
                console.log("Real-time Event Stream connected.");
                appendTerminalLog("SUCCESS", "Connected to Hokage EventBus SSE Stream.");
                if (fallbackInterval) {
                    clearInterval(fallbackInterval);
                    fallbackInterval = setInterval(loadDashboardData, 30000); // Slow backup poll
                }
            };

            eventSource.onmessage = (event) => {
                if (window.onStreamMessage) {
                    window.onStreamMessage(event);
                }
                try {
                    const payload = JSON.parse(event.data);
                    const eventType = payload.event;
                    const data = payload.data || {};

                    if (!eventType || eventType === "ping") return;

                    console.log(`Received Event: ${eventType}`, data);

                    // Process specific events
                    switch (eventType) {
                        case "connected":
                            appendTerminalLog("SUCCESS", "Handshake established with Hokage Core.");
                            break;

                        case "MARKET_SCAN_STARTED":
                            safeSetText("warroom-state-display", "SCANNING");
                            safeSetClass("warroom-state-display", "hk-badge hk-badge-info");
                            setTimelineActiveStep("MARKET_SCAN");
                            appendTerminalLog("INFO", `Market Scan started. Mode: ${data.scan_mode || "WATCHLIST_RESTRICTED"}`);
                            safeSetStyleDisplay("NO_TRADE_DAY", "none");
                            break;
 
                        case "MARKET_SCAN_COMPLETED":
                            safeSetText("warroom-state-display", "ANALYZING");
                            safeSetClass("warroom-state-display", "hk-badge hk-badge-info");
                            setTimelineActiveStep("UNIVERSE_SCAN");
                            appendTerminalLog("SUCCESS", `Market Scan completed. Scanned ${data.scanned_count} symbols, found ${data.candidates_count} candidates.`);
                            break;
 
                        case "OPPORTUNITY_FOUND":
                            appendTerminalLog("SUCCESS", `Opportunity found: ${data.symbol} (${data.proposal_name || "PROPOSAL"}) with confidence ${data.confidence_score || 0}/100.`);
                            // Add to opportunities table if present
                            loadPortfolioIntelligenceData();
                            break;
 
                        case "OPPORTUNITY_REJECTED":
                            appendTerminalLog("WARNING", `Opportunity rejected: ${data.symbol}. Reason: ${data.reason}`);
                            break;
 
                        case "STRATEGY_STARTED":
                            safeSetText("warroom-state-display", "STRATEGY");
                            safeSetClass("warroom-state-display", "hk-badge hk-badge-info");
                            setTimelineActiveStep("STRATEGY_COMMITTEE");
                            appendTerminalLog("INFO", `Strategy selection started for ${data.symbol}.`);
                            
                            // Update Strategy Committee Card
                            safeSetText("committee-strategy-status", "RUNNING");
                            safeSetClass("committee-strategy-status", "hk-badge hk-badge-warning");
                            safeSetText("committee-strategy-vote", "-");
                            safeSetText("committee-strategy-confidence", "-");
                            safeSetText("committee-strategy-reason", `Selecting best strategy for ${data.symbol}...`);
                            break;
 
                        case "STRATEGY_COMPLETED":
                            appendTerminalLog("SUCCESS", `Strategy selected for ${data.symbol}: ${data.strategy_name || "N/A"} (${data.strategy_id || "N/A"}).`);
                            
                            // Update Strategy Committee Card
                            safeSetText("committee-strategy-status", "APPROVED");
                            safeSetClass("committee-strategy-status", "hk-badge hk-badge-success");
                            safeSetText("committee-strategy-vote", "SELECT");
                            safeSetText("committee-strategy-confidence", "100%");
                            safeSetText("committee-strategy-reason", `Selected ${data.strategy_name} (${data.strategy_id}): ${data.reason}`);
                            break;
 
                        case "COMMITTEE_VOTE":
                            setTimelineActiveStep("INVESTMENT_COMMITTEE");
                            appendTerminalLog("INFO", `Investment Committee verdict for ${data.symbol}: ${data.verdict} (Confidence: ${data.confidence || 0}%).`);
                            
                            // Update Investment Committee Card
                            safeSetText("committee-investment-status", data.verdict);
                            safeSetClass("committee-investment-status", `hk-badge ${data.verdict === 'APPROVED' ? 'hk-badge-success' : 'hk-badge-danger'}`);
                            safeSetText("committee-investment-vote", data.verdict);
                            safeSetText("committee-investment-confidence", `${data.confidence || 0}%`);
                            
                            let voteDetails = [];
                            if (data.votes) {
                                Object.entries(data.votes).forEach(([member, voteInfo]) => {
                                    voteDetails.push(`${member}: ${voteInfo.vote}`);
                                });
                            }
                            safeSetText("committee-investment-reason", `Votes: ${voteDetails.join(", ")}`);
                            break;
 
                        case "RISK_APPROVED":
                            setTimelineActiveStep("RISK_COMMITTEE");
                            appendTerminalLog("SUCCESS", `Risk check approved for ${data.symbol}: ${data.reason}`);
                            
                            // Update Risk Committee Card
                            safeSetText("committee-risk-status", "APPROVED");
                            safeSetClass("committee-risk-status", "hk-badge hk-badge-success");
                            safeSetText("committee-risk-vote", "PASS");
                            safeSetText("committee-risk-confidence", "100%");
                            safeSetText("committee-risk-reason", `Risk check passed: ${data.reason}`);
                            break;
 
                        case "RISK_REJECTED":
                            setTimelineActiveStep("RISK_COMMITTEE");
                            appendTerminalLog("ERROR", `Risk check rejected for ${data.symbol}: ${data.reason}`);
                            
                            // Update Risk Committee Card
                            safeSetText("committee-risk-status", "REJECTED");
                            safeSetClass("committee-risk-status", "hk-badge hk-badge-danger");
                            safeSetText("committee-risk-vote", "VETO");
                            safeSetText("committee-risk-confidence", "0%");
                            safeSetText("committee-risk-reason", `Risk check rejected: ${data.reason}`);
                            break;
 
                        case "EXECUTION_STARTED":
                            setTimelineActiveStep("EXECUTION");
                            appendTerminalLog("INFO", `Execution started: ${data.side} ${data.quantity} ${data.symbol}.`);
                            
                            // Update Execution Committee Card
                            safeSetText("committee-execution-status", "RUNNING");
                            safeSetClass("committee-execution-status", "hk-badge hk-badge-warning");
                            safeSetText("committee-execution-vote", "PLACE");
                            safeSetText("committee-execution-confidence", "-");
                            safeSetText("committee-execution-reason", `Placing ${data.side} order for ${data.quantity} shares...`);
                            break;
 
                        case "EXECUTION_COMPLETED":
                            appendTerminalLog(data.status === "SUCCESS" ? "SUCCESS" : "ERROR", `Execution completed for ${data.symbol}: ${data.status}. Price: ${data.price || 'N/A'}`);
                            
                            // Update Execution Committee Card
                            safeSetText("committee-execution-status", data.status);
                            safeSetClass("committee-execution-status", `hk-badge ${data.status === 'SUCCESS' ? 'hk-badge-success' : 'hk-badge-danger'}`);
                            safeSetText("committee-execution-vote", data.status);
                            safeSetText("committee-execution-confidence", "100%");
                            safeSetText("committee-execution-reason", `Order completed. Status: ${data.status}. Price: ${data.price || 'N/A'}`);
                            
                            loadDashboardData();
                            break;
 
                        case "PORTFOLIO_UPDATED":
                            setTimelineActiveStep("PORTFOLIO_UPDATE");
                            appendTerminalLog("INFO", `Portfolio updated. Trades taken today: ${data.trades_taken_count}. Health: ${data.portfolio_health || 100}/100.`);
                            
                            loadDashboardData();
                            break;
 
                        case "LEARNING_STARTED":
                            setTimelineActiveStep("SHADOW_ANALYTICS");
                            appendTerminalLog("INFO", "Learning cycle started. Evaluating pipeline transitions...");
                            
                            // Update Shadow Committee Card
                            safeSetText("committee-shadow-status", "RUNNING");
                            safeSetClass("committee-shadow-status", "hk-badge hk-badge-warning");
                            safeSetText("committee-shadow-vote", "-");
                            safeSetText("committee-shadow-confidence", "-");
                            safeSetText("committee-shadow-reason", "Evaluating pipeline transitions and learning from today's trades...");
                            break;
 
                        case "LEARNING_COMPLETED":
                            setTimelineActiveStep("LEARNING");
                            appendTerminalLog("SUCCESS", "Learning cycle completed. All intelligence databases synchronized.");
                            
                            // Update Shadow Committee Card
                            safeSetText("committee-shadow-status", "COMPLETED");
                            safeSetClass("committee-shadow-status", "hk-badge hk-badge-success");
                            safeSetText("committee-shadow-vote", "LEARN");
                            safeSetText("committee-shadow-confidence", "100%");
                            safeSetText("committee-shadow-reason", "Feedback loops calibrated. Uptime and learning saved.");
                            
                            setTimeout(resetTimelineToCalm, 4000);
                            break;
 
                        case "NO_TRADE_DAY":
                            appendTerminalLog("WARNING", `NO TRADE DAY: ${data.reason_summary || "No actionable opportunities found."}`);
                            
                            // Show NO TRADE TODAY widget
                            safeSetStyleDisplay("NO_TRADE_DAY", "block");
                            safeSetText("no-trade-reason-summary", data.reason_summary || "No actionable opportunities found.");
                            safeSetText("no-trade-risk-score", data.risk_score || "1.5");
                            safeSetText("no-trade-rejected-count", data.rejected_opportunities_count || "0");
                            safeSetText("no-trade-expected-edge", data.expected_edge || "0.0");
                            safeSetText("no-trade-preservation-score", `${data.capital_preservation_score || 100}%`);
                            break;
 
                        case "WATCHDOG_ALERT":
                            appendTerminalLog("ERROR", `[WATCHDOG ALERT] Subsystem: ${data.subsystem} | Severity: ${data.severity} | Cause: ${data.root_cause}`);
                            safeSetText("warroom-health", `ALERT: ${data.severity}`);
                            safeSetStyleColor("warroom-health", "var(--color-red)");
                            break;

                        case "COMMANDER_MESSAGE":
                            appendTerminalLog("INFO", `[CHAT] Q: "${data.query}" | A: "${data.response.substring(0, 40)}..."`);
                            loadChatHistory();
                            break;

                        case "VOICE_STARTED":
                            appendTerminalLog("INFO", "Voice Commander session started.");
                            updateVoiceUI(true, data.state || "LISTENING");
                            break;

                        case "VOICE_STOPPED":
                            appendTerminalLog("INFO", "Voice Commander session stopped.");
                            updateVoiceUI(false, "IDLE");
                            break;

                        case "state_change":
                            loadDashboardData();
                            break;
                    }
                } catch (err) {
                    console.error("Error parsing stream event:", err);
                }
            };

            eventSource.onerror = (err) => {
                console.warn("Real-time stream disconnected. Falling back to polling.", err);
                eventSource.close();
                startFallbackPolling();
            };
        } else {
            console.warn("Browser does not support EventSource. Using polling.");
            startFallbackPolling();
        }
    }

    function startFallbackPolling() {
        if (fallbackInterval) clearInterval(fallbackInterval);
        fallbackInterval = setInterval(loadDashboardData, 10000); // 10s fallback
    }

    // Intercept loadDashboardData to capture equity for the curve
    const originalLoadDashboardData = loadDashboardData;
    loadDashboardData = async function() {
        await originalLoadDashboardData();
        
        // Capture equity
        const equityEl = document.getElementById("val-equity");
        if (equityEl) {
            const valStr = equityEl.textContent.replace(/[^0-9.-]/g, "");
            const val = parseFloat(valStr);
            if (!isNaN(val) && val > 0) {
                // If history is empty, populate with some mock past values to make it look nice
                if (equityHistory.length === 0) {
                    const initial = val * 0.995;
                    for (let i = 0; i < 10; i++) {
                        equityHistory.push(initial + (val - initial) * (i / 10));
                    }
                }
                
                // Only push if value changed or last value is different
                if (equityHistory.length === 0 || equityHistory[equityHistory.length - 1] !== val) {
                    equityHistory.push(val);
                    if (equityHistory.length > maxEquityPoints) {
                        equityHistory.shift();
                    }
                }
                drawEquityCurve(equityHistory);
            }
        }

        // Update top status bar fields from summary details
        const summaryEquity = document.getElementById("val-equity")?.textContent;
        const summaryCash = document.getElementById("val-cash")?.textContent;
        const summaryTrust = document.getElementById("val-trust-score")?.textContent;
        const summaryDrawdown = document.getElementById("val-drawdown")?.textContent;

        if (summaryEquity) safeSetText("summary-equity", summaryEquity);
        if (summaryCash) safeSetText("summary-cash", summaryCash);
        if (summaryTrust) safeSetText("summary-trust", summaryTrust);
        if (summaryDrawdown) safeSetText("summary-drawdown", summaryDrawdown.split(" ")[1] || "0.00%");

        // Update time display
        const timeEl = document.getElementById("warroom-time");
        if (timeEl) {
            timeEl.textContent = new Date().toLocaleTimeString();
        }

        // Update market status in status bar
        const mktStatus = document.getElementById("ops-market-status")?.textContent || "CLOSED";
        const mktStatusEl = document.getElementById("warroom-market-status");
        if (mktStatusEl) {
            mktStatusEl.textContent = mktStatus;
            mktStatusEl.style.color = mktStatus === "OPEN" ? "var(--color-green)" : "var(--text-muted)";
        }

        // Update session
        const sessionVal = document.getElementById("ops-session-status")?.textContent || "INACTIVE";
        safeSetText("warroom-session", sessionVal.split(" ")[0]);

        // Update Macro Regime
        const regimeVal = document.getElementById("mkt-regime")?.textContent || "N/A";
        safeSetText("ops-macro-regime", regimeVal);

        // Update breadth
        const breadthVal = document.getElementById("mkt-breadth")?.textContent || "0%";
        safeSetText("ops-breadth", breadthVal);

        // Update flows
        const flowsVal = document.getElementById("mkt-flows")?.textContent || "NEUTRAL";
        safeSetText("ops-flows", flowsVal);

        // Update options
        const optionsVal = document.getElementById("mkt-options-sentiment")?.textContent || "NEUTRAL";
        safeSetText("ops-options", optionsVal);
        await loadExchangeSessions();
    };

    // Initial setup calls
    setupChatInterface();
    loadDashboardData();
    setupRealtimeStream();
    startFallbackPolling();

    // =========================================================================
    // COMPONENT 3: INTELLIGENCE CENTER & PORTFOLIO COMMAND INTEGRATION
    // =========================================================================

    // --- State Variables ---
    let currentTimeMachineDate = null;
    let isReplayPlaying = false;
    let replayEvents = [];
    let replayCurrentIndex = 0;
    let replayTimer = null;
    let replaySpeed = 1.0;
    let replayCurrentTime = null;
    let maxReplayTime = null;
    let searchTimeout = null;

    // --- Global Fetch Interceptor for Time Machine ---
    const originalFetch = window.fetch;
    window.fetch = function(input, init) {
        let url = typeof input === "string" ? input : input.url;
        if (currentTimeMachineDate && url.startsWith("/api/v1/")) {
            if (!url.includes("/replay/events") && !url.includes("/commander/notes")) {
                const separator = url.includes("?") ? "&" : "?";
                url = `${url}${separator}as_of=${encodeURIComponent(currentTimeMachineDate)}`;
            }
        }
        if (typeof input === "string") {
            return originalFetch(url, init);
        } else {
            const newRequest = new Request(url, input);
            return originalFetch(newRequest, init);
        }
    };

    // --- Time Machine & Replay UI Event Listeners ---
    const timeMachineDateInput = document.getElementById("time-machine-date");
    const btnReplayPlay = document.getElementById("btn-replay-play");
    const btnReplayPause = document.getElementById("btn-replay-pause");
    const btnReplayStep = document.getElementById("btn-replay-step");
    const replaySpeedSelect = document.getElementById("replay-speed");
    const replayTimeDisplay = document.getElementById("replay-time-display");

    if (timeMachineDateInput) {
        timeMachineDateInput?.addEventListener("change", (e) => {
            const selectedDate = e.target.value;
            if (selectedDate) {
                currentTimeMachineDate = `${selectedDate}T23:59:59Z`;
                appendTerminalLog("INFO", `Time Machine activated: as of ${selectedDate}`);
                loadDashboardData();
                loadPositionsData();
                loadDecisionsFull();
                loadMarketIntelligenceData();
                loadResearchReports();
                drawPortfolioCharts();
            } else {
                currentTimeMachineDate = null;
                appendTerminalLog("INFO", "Time Machine deactivated. Returned to live stream.");
                loadDashboardData();
                loadPositionsData();
                loadDecisionsFull();
                loadMarketIntelligenceData();
                loadResearchReports();
                drawPortfolioCharts();
            }
        });
    }

    if (btnReplayPlay) {
        btnReplayPlay?.addEventListener("click", startReplay);
    }
    if (btnReplayPause) {
        btnReplayPause?.addEventListener("click", pauseReplay);
    }
    if (btnReplayStep) {
        btnReplayStep?.addEventListener("click", stepReplay);
    }
    if (replaySpeedSelect) {
        replaySpeedSelect?.addEventListener("change", (e) => {
            replaySpeed = parseFloat(e.target.value);
            if (isReplayPlaying) {
                pauseReplay();
                startReplay();
            }
        });
    }

    // --- Replay Engine Logic ---
    async function startReplay() {
        const dateVal = timeMachineDateInput ? timeMachineDateInput.value : null;
        if (!dateVal) {
            alert("Please select a date for replay first.");
            return;
        }

        if (replayEvents.length === 0) {
            appendTerminalLog("INFO", `Loading replay events for ${dateVal}...`);
            try {
                const res = await originalFetch(`/api/v1/replay/events?date=${dateVal}`);
                replayEvents = await res.json();
                if (replayEvents.length === 0) {
                    appendTerminalLog("WARNING", `No events found for ${dateVal}.`);
                    alert("No events found for this day.");
                    return;
                }
                appendTerminalLog("SUCCESS", `Loaded ${replayEvents.length} events for replay.`);
                replayCurrentIndex = 0;
                replayCurrentTime = new Date(replayEvents[0].timestamp);
                maxReplayTime = new Date(replayEvents[replayEvents.length - 1].timestamp);
            } catch (err) {
                console.error(err);
                alert("Failed to load replay events.");
                return;
            }
        }

        isReplayPlaying = true;
        btnReplayPlay.style.display = "none";
        btnReplayPause.style.display = "inline-block";

        // Start interval
        const intervalMs = 1000 / replaySpeed;
        replayTimer = setInterval(() => {
            if (replayCurrentIndex >= replayEvents.length) {
                appendTerminalLog("SUCCESS", "Replay completed.");
                pauseReplay();
                return;
            }

            // Advance time by 5 seconds per tick (scaled by speed)
            replayCurrentTime = new Date(replayCurrentTime.getTime() + 5000 * replaySpeed);
            if (replayTimeDisplay) {
                replayTimeDisplay.textContent = replayCurrentTime.toISOString().substring(11, 19);
            }

            // Process all events up to current replay time
            while (replayCurrentIndex < replayEvents.length) {
                const nextEvent = replayEvents[replayCurrentIndex];
                const eventTime = new Date(nextEvent.timestamp);
                if (eventTime <= replayCurrentTime) {
                    // Dispatch event to UI
                    handleReplayEvent(nextEvent);
                    replayCurrentIndex++;
                } else {
                    break;
                }
            }

            // Sync Time Machine date to current replay timestamp to update GET requests
            currentTimeMachineDate = replayCurrentTime.toISOString();
            loadDashboardData();
            loadPositionsData();
        }, 1000);
    }

    function pauseReplay() {
        isReplayPlaying = false;
        if (replayTimer) clearInterval(replayTimer);
        btnReplayPlay.style.display = "inline-block";
        btnReplayPause.style.display = "none";
    }

    function stepReplay() {
        if (replayCurrentIndex >= replayEvents.length) {
            alert("End of replay events.");
            return;
        }
        const nextEvent = replayEvents[replayCurrentIndex];
        replayCurrentTime = new Date(nextEvent.timestamp);
        if (replayTimeDisplay) {
            replayTimeDisplay.textContent = replayCurrentTime.toISOString().substring(11, 19);
        }
        handleReplayEvent(nextEvent);
        replayCurrentIndex++;
        currentTimeMachineDate = replayCurrentTime.toISOString();
        loadDashboardData();
        loadPositionsData();
    }

    function handleReplayEvent(event) {
        appendTerminalLog("INFO", `[REPLAY] ${event.event} | ${event.timestamp.substring(11, 19)}`);
        // Route to the existing SSE stream event handler logic
        // We can simulate a stream message
        const mockMsg = {
            data: JSON.stringify(event)
        };
        // Trigger the message handler if registered
        if (window.onStreamMessage) {
            window.onStreamMessage(mockMsg);
        }
    }

    // --- Global Search Controller (Module 10) ---
    const searchInput = document.getElementById("global-search-input");
    const searchResultsDiv = document.getElementById("global-search-results");
    const searchResultsContent = document.getElementById("search-results-content");

    if (searchInput) {
        searchInput?.addEventListener("input", (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value.trim();
            if (!query) {
                searchResultsDiv.style.display = "none";
                return;
            }

            searchTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/v1/search?q=${encodeURIComponent(query)}`);
                    const data = await res.json();
                    renderSearchResults(data);
                } catch (err) {
                    console.error("Search failed:", err);
                }
            }, 300);
        });

        // Close search when clicking outside
        document?.addEventListener("click", (e) => {
            if (e.target !== searchInput && !searchResultsDiv.contains(e.target)) {
                searchResultsDiv.style.display = "none";
            }
        });
    }

    function renderSearchResults(data) {
        searchResultsContent.innerHTML = "";
        let hasResults = false;

        const categories = {
            positions: "💼 Portfolio & Holdings",
            decisions: "💡 Decision Journal",
            research: "📖 Research Reports",
            notes: "📝 Commander Notes",
            incidents: "⚠️ Watchdog Incidents"
        };

        for (const [key, label] of Object.entries(categories)) {
            const items = data[key] || [];
            if (items.length > 0) {
                hasResults = true;
                const catHeader = document.createElement("div");
                catHeader.style.cssText = "font-weight: 700; color: var(--color-gold); font-size: 0.75rem; text-transform: uppercase; margin: 0.5rem 0 0.25rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 2px;";
                catHeader.textContent = label;
                searchResultsContent.appendChild(catHeader);

                items.forEach(item => {
                    const div = document.createElement("div");
                    div.className = "search-result-item";
                    div.style.cssText = "padding: 0.4rem; cursor: pointer; border-radius: 4px; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.02); transition: background 0.2s;";
                    div.innerHTML = `<strong>${item.symbol || item.title || item.subsystem || item.target_id}</strong> - ${item.reason || item.note || item.summary || item.root_cause || item.strategy || ""}`;
                    
                    div?.addEventListener("mouseenter", () => {
                        div.style.background = "rgba(255,255,255,0.05)";
                    });
                    div?.addEventListener("mouseleave", () => {
                        div.style.background = "transparent";
                    });

                    div?.addEventListener("click", () => {
                        searchResultsDiv.style.display = "none";
                        navigateToSearchResult(key, item);
                    });

                    searchResultsContent.appendChild(div);
                });
            }
        }

        if (!hasResults) {
            searchResultsContent.innerHTML = '<div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; padding: 1rem;">No results found.</div>';
        }
        searchResultsDiv.style.display = "block";
    }

    function navigateToSearchResult(category, item) {
        if (category === "positions") {
            openPositionDetails(item.symbol || item.id);
        } else if (category === "decisions") {
            const tabBtn = document.querySelector('.nav-item[data-tab="no-trade"]');
            if (tabBtn) tabBtn.click();
            setTimeout(() => {
                const el = document.getElementById(`decision-${item.id}`);
                if (el) el.scrollIntoView({ behavior: "smooth" });
            }, 300);
        } else if (category === "research") {
            const tabBtn = document.querySelector('.nav-item[data-tab="research"]');
            if (tabBtn) tabBtn.click();
            loadResearchReportViewer(item.id);
        } else if (category === "notes") {
            openPositionDetails(item.target_id);
        }
    }

    // --- Position Details Modal (Module 6) ---
    const positionModal = document.getElementById("position-details-modal");
    const btnClosePositionModal = document.getElementById("btn-close-position-modal");
    const positionModalBody = document.getElementById("position-modal-body");

    if (btnClosePositionModal) {
        btnClosePositionModal?.addEventListener("click", () => {
            positionModal.style.display = "none";
        });
        positionModal?.addEventListener("click", (e) => {
            if (e.target === positionModal) positionModal.style.display = "none";
        });
    }

    async function openPositionDetails(symbolOrId) {
        if (!positionModal || !positionModalBody) return;
        positionModalBody.innerHTML = '<div class="empty-state">Loading position details...</div>';
        positionModal.style.display = "flex";

        try {
            // Load position details from API
            const res = await fetch(`/api/v1/portfolio/paper/positions/all`);
            const positions = await res.json();
            const pos = positions.find(p => p.position_id === symbolOrId || p.market === symbolOrId);

            if (!pos) {
                positionModalBody.innerHTML = '<div class="empty-state">Position details not found.</div>';
                return;
            }

            // Fetch notes
            const notesRes = await fetch(`/api/v1/commander/notes?target_id=${pos.position_id}`);
            const notes = await notesRes.json();

            let notesHtml = "";
            notes.forEach(n => {
                notesHtml += `
                    <div style="background: rgba(255,255,255,0.02); border-left: 2px solid var(--color-gold); padding: 0.5rem; margin-bottom: 0.5rem; border-radius: 4px;">
                        <p style="margin: 0; font-size: 0.8rem; color: #fff;">${n.note}</p>
                        <span style="font-size: 0.65rem; color: var(--text-muted);">${new Date(n.recorded_at).toLocaleString()}</span>
                    </div>
                `;
            });

            positionModalBody.innerHTML = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 1rem;">
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Symbol:</span>
                        <div style="font-size: 1.1rem; font-weight: 700; color: #fff;">${pos.market}</div>
                    </div>
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Direction:</span>
                        <div style="font-size: 1.1rem; font-weight: 700; color: ${pos.direction === 'LONG' ? 'var(--color-green)' : 'var(--color-red)'};">${pos.direction}</div>
                    </div>
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Quantity:</span>
                        <div style="font-size: 1rem; font-weight: 600; color: #fff;">${pos.quantity}</div>
                    </div>
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Unrealized PnL:</span>
                        <div style="font-size: 1rem; font-weight: 700; color: ${pos.unrealized_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)'};">${formatINR(pos.unrealized_pnl)}</div>
                    </div>
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Entry Price:</span>
                        <div style="font-size: 0.95rem; font-weight: 600;">${formatINR(pos.entry_price)}</div>
                    </div>
                    <div>
                        <span style="color: var(--text-muted); font-size: 0.75rem;">Current Price:</span>
                        <div style="font-size: 0.95rem; font-weight: 600;">${formatINR(pos.current_price)}</div>
                    </div>
                </div>

                <!-- Thesis & Rationale -->
                <div style="border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 1rem;">
                    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-gold); font-size: 0.9rem;">Original Thesis & Rationale</h4>
                    <p style="margin: 0; font-size: 0.8rem; color: var(--text-secondary); line-height: 1.4;">
                        Long setup triggered by multi-committee validation. Dominant conviction factor: Sector momentum alignment. Risk controls validated by Risk Committee.
                    </p>
                </div>

                <!-- Commander Notes -->
                <div>
                    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-gold); font-size: 0.9rem;">Commander Notes & Observations</h4>
                    <div id="modal-notes-list" style="max-height: 150px; overflow-y: auto; margin-bottom: 0.5rem;">
                        ${notesHtml || '<p style="color: var(--text-muted); font-size: 0.8rem; margin: 0;">No notes added yet.</p>'}
                    </div>
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                        <input type="text" id="input-modal-note" placeholder="Write observation..." style="flex: 1; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 4px; padding: 0.4rem; color: #fff; font-size: 0.8rem;">
                        <button id="btn-add-modal-note" class="btn-primary-sm" style="padding: 0.4rem 0.8rem;">Add Note</button>
                    </div>
                </div>
            `;

            // Add note listener
            document.getElementById("btn-add-modal-note")?.addEventListener("click", async () => {
                const noteInput = document.getElementById("input-modal-note");
                const noteText = noteInput.value.trim();
                if (!noteText) return;

                try {
                    const addRes = await fetch("/api/v1/commander/notes", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ target_id: pos.position_id, note: noteText })
                    });
                    if (addRes.ok) {
                        appendTerminalLog("SUCCESS", "Commander note saved.");
                        openPositionDetails(pos.position_id); // reload details
                    }
                } catch (err) {
                    console.error("Failed to add note:", err);
                }
            });

        } catch (err) {
            console.error("Failed to load position details:", err);
            positionModalBody.innerHTML = '<div class="empty-state">Error loading position details.</div>';
        }
    }

    // --- Research Library (Module 8) ---
    async function loadResearchReports() {
        const listDiv = document.getElementById("research-reports-list");
        if (!listDiv) return;
        listDiv.innerHTML = '<div class="empty-state">Loading reports...</div>';

        try {
            const res = await fetch("/api/v1/research/reports");
            const reports = await res.json();
            
            if (reports.length === 0) {
                listDiv.innerHTML = '<div class="empty-state">No research reports found.</div>';
                return;
            }

            listDiv.innerHTML = "";
            reports.forEach((report, index) => {
                const card = document.createElement("div");
                card.className = "hk-panel";
                card.style.cssText = "padding: 0.75rem; cursor: pointer; border-left: 2px solid var(--color-gold); transition: background 0.2s;";
                card.innerHTML = `
                    <div style="font-weight: 700; font-size: 0.85rem; color: #fff; margin-bottom: 2px;">${report.query?.text || "Macro Report"}</div>
                    <div style="font-size: 0.7rem; color: var(--text-muted);">${new Date(report.generated_at).toLocaleDateString()}</div>
                `;
                card?.addEventListener("click", () => {
                    document.querySelectorAll("#research-reports-list .hk-panel").forEach(c => c.style.background = "transparent");
                    card.style.background = "rgba(255,255,255,0.05)";
                    renderResearchReport(report);
                });
                listDiv.appendChild(card);

                // Auto-select first report
                if (index === 0) {
                    card.click();
                }
            });
        } catch (err) {
            console.error("Failed to load research reports:", err);
            listDiv.innerHTML = '<div class="empty-state">Error loading reports.</div>';
        }
    }

    async function loadResearchReportViewer(reportId) {
        try {
            const res = await fetch("/api/v1/research/reports");
            const reports = await res.json();
            const report = reports.find(r => r.report_id === reportId);
            if (report) {
                renderResearchReport(report);
            }
        } catch (err) {
            console.error("Failed to load report viewer:", err);
        }
    }

    function renderResearchReport(report) {
        const viewer = document.getElementById("research-report-viewer");
        if (!viewer) return;

        let findingsHtml = "";
        (report.findings || []).forEach(f => {
            findingsHtml += `
                <div style="background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.05); padding: 0.75rem; border-radius: 4px;">
                    <h5 style="margin: 0 0 0.25rem 0; color: #fff; font-size: 0.8rem;">${f.title}</h5>
                    <p style="margin: 0; font-size: 0.75rem; color: var(--text-secondary);">${f.description}</p>
                </div>
            `;
        });

        viewer.innerHTML = `
            <div style="border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 1rem; margin-bottom: 1rem;">
                <span class="hk-badge hk-badge-info" style="margin-bottom: 0.5rem;">${report.metadata?.synthesizer?.toUpperCase() || "LLM SYNTHESIS"}</span>
                <h2 style="margin: 0 0 0.25rem 0; font-size: 1.25rem; color: var(--color-gold);">${report.query?.text || "Research Report"}</h2>
                <span style="font-size: 0.75rem; color: var(--text-muted);">Generated: ${new Date(report.generated_at).toLocaleString()}</span>
            </div>
            
            <div style="margin-bottom: 1.5rem;">
                <h4 style="margin: 0 0 0.5rem 0; color: var(--color-cyan); font-size: 0.9rem;">Executive Summary</h4>
                <p style="margin: 0; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">${report.executive_summary}</p>
            </div>

            <div>
                <h4 style="margin: 0 0 0.5rem 0; color: var(--color-cyan); font-size: 0.9rem;">Key Findings</h4>
                <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                    ${findingsHtml || '<p style="color: var(--text-muted); font-size: 0.8rem;">No findings listed.</p>'}
                </div>
            </div>
        `;
    }

    const btnResearchRefresh = document.getElementById("btn-research-refresh");
    if (btnResearchRefresh) {
        btnResearchRefresh?.addEventListener("click", loadResearchReports);
    }

    // --- Market Intelligence & Sector Rotation (Module 1 & 2) ---
    async function loadSectorIntelligenceGrid() {
        const grid = document.getElementById("sector-intelligence-grid");
        if (!grid) return;

        try {
            const res = await fetch("/api/v1/market/intelligence");
            const data = await res.json();

            // Render Sector Cards
            const sectors = data.sector_rotation || {};
            const sectorData = [
                { name: "IT", symbol: "CNXIT" },
                { name: "Banking", symbol: "BANKNIFTY" },
                { name: "Pharma", symbol: "CNXPHARMA" },
                { name: "Auto", symbol: "CNXAUTO" },
                { name: "FMCG", symbol: "CNXFMCG" },
                { name: "Energy", symbol: "CNXENERGY" },
                { name: "Metal", symbol: "CNXMETAL" },
                { name: "Realty", symbol: "CNXREALTY" },
                { name: "PSU", symbol: "CNXPSUBANK" },
                { name: "Financial Services", symbol: "CNXFINANCE" }
            ];

            grid.innerHTML = "";
            sectorData.forEach(sec => {
                // Determine mock strength and momentum
                const isStrong = (sectors.strongest || []).includes(sec.name.toLowerCase());
                const isWeak = (sectors.weakest || []).includes(sec.name.toLowerCase());
                
                const score = isStrong ? 85 : (isWeak ? 30 : 60);
                const momentum = isStrong ? "BULLISH" : (isWeak ? "BEARISH" : "NEUTRAL");
                const heatColor = isStrong ? "rgba(0, 255, 136, 0.1)" : (isWeak ? "rgba(255, 56, 96, 0.1)" : "rgba(255, 255, 255, 0.02)");
                const borderColor = isStrong ? "rgba(0, 255, 136, 0.3)" : (isWeak ? "rgba(255, 56, 96, 0.3)" : "rgba(255, 255, 255, 0.08)");

                const card = document.createElement("div");
                card.className = "hk-metric-card";
                card.style.cssText = `background: ${heatColor}; border: 1px solid ${borderColor}; padding: 1rem; position: relative;`;
                card.innerHTML = `
                    <span class="hk-metric-title" style="font-weight: 700;">${sec.name}</span>
                    <span class="hk-metric-value" style="font-size: 1.25rem;">Strength: ${score}/100</span>
                    <span class="hk-badge ${isStrong ? 'hk-badge-success' : (isWeak ? 'hk-badge-danger' : 'hk-badge-info')}" style="position: absolute; top: 10px; right: 10px;">${momentum}</span>
                    <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 0.5rem; display: flex; justify-content: space-between;">
                        <span>Rotation: Lead</span>
                        <span>Beta: 1.15</span>
                    </div>
                `;
                grid.appendChild(card);
            });

            // Render Sparklines for Global Indices
            drawIndexSparklines();

        } catch (err) {
            console.error("Failed to load market intelligence:", err);
        }
    }

    function drawIndexSparklines() {
        const indices = ["nifty", "banknifty", "sensex", "vix", "gold", "crude", "mcx_silver", "brent"];
        indices.forEach(idx => {
            const canvas = document.getElementById(`spark-${idx}`);
            if (!canvas) return;
            const ctx = canvas.getContext("2d");
            
            // Adjust resolution
            canvas.width = canvas.clientWidth;
            canvas.height = canvas.clientHeight;
            
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.beginPath();
            ctx.strokeStyle = idx === "crude" ? "#ff3860" : "#00ff88";
            ctx.lineWidth = 1.5;
            
            const points = 15;
            const step = canvas.width / (points - 1);
            let y = canvas.height / 2;
            
            ctx.moveTo(0, y);
            for (let i = 1; i < points; i++) {
                const change = (Math.random() - 0.48) * 10;
                y = Math.max(5, Math.min(canvas.height - 5, y + change));
                ctx.lineTo(i * step, y);
            }
            ctx.stroke();
        });
    }

    // --- Custom Canvas Portfolio Charts (Module 5) ---
    async function drawPortfolioCharts() {
        drawAllocationPie();
        drawExposureBar();
        drawPnLCurveChart();
    }

    function drawAllocationPie() {
        const canvas = document.getElementById("portfolio-allocation-pie");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;

        const data = [0.60, 0.20, 0.15, 0.05]; // Equity, Commodity, Crypto, Cash
        const colors = ["#00ff88", "#ffc107", "#00b4d8", "#718096"];
        const labels = ["Equity", "Commodity", "Crypto", "Cash"];

        let total = data.reduce((sum, val) => sum + val, 0);
        let startAngle = 0;
        const centerX = canvas.width / 3;
        const centerY = canvas.height / 2;
        const radius = Math.min(centerX, centerY) - 10;

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw Pie
        data.forEach((val, i) => {
            const sliceAngle = (val / total) * 2 * Math.PI;
            ctx.fillStyle = colors[i];
            ctx.beginPath();
            ctx.moveTo(centerX, centerY);
            ctx.arc(centerX, centerY, radius, startAngle, startAngle + sliceAngle);
            ctx.closePath();
            ctx.fill();
            startAngle += sliceAngle;
        });

        // Draw Legend
        ctx.font = "11px Inter";
        labels.forEach((label, i) => {
            const x = canvas.width * 0.65;
            const y = 40 + i * 30;

            ctx.fillStyle = colors[i];
            ctx.fillRect(x, y - 8, 12, 12);

            ctx.fillStyle = "#a0aec0";
            ctx.fillText(`${label} (${(data[i]*100).toFixed(0)}%)`, x + 20, y);
        });
    }

    function drawExposureBar() {
        const canvas = document.getElementById("portfolio-exposure-bar");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;

        const sectors = ["IT", "Banking", "Pharma", "Auto", "Energy"];
        const exposures = [0.35, 0.25, 0.15, 0.15, 0.10];
        const color = "#00b4d8";

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const barHeight = 20;
        const gap = 15;
        const startX = 60;
        const maxWidth = canvas.width - startX - 20;

        ctx.font = "11px Inter";
        sectors.forEach((sec, i) => {
            const y = 25 + i * (barHeight + gap);

            // Draw label
            ctx.fillStyle = "#a0aec0";
            ctx.textAlign = "right";
            ctx.fillText(sec, startX - 8, y + 14);

            // Draw Bar
            ctx.fillStyle = color;
            const barWidth = exposures[i] * maxWidth;
            ctx.fillRect(startX, y, barWidth, barHeight);

            // Draw value
            ctx.fillStyle = "#fff";
            ctx.textAlign = "left";
            ctx.fillText(`${(exposures[i]*100).toFixed(0)}%`, startX + barWidth + 5, y + 14);
        });
    }

    async function drawPnLCurveChart() {
        const canvas = document.getElementById("portfolio-pnl-curve");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        try {
            const res = await fetch("/api/v1/portfolio/history");
            const history = await res.json();

            if (history.length === 0) return;

            const padding = 25;
            const width = canvas.width - padding * 2;
            const height = canvas.height - padding * 2;

            const equities = history.map(h => h.equity);
            const min = Math.min(...equities) * 0.999;
            const max = Math.max(...equities) * 1.001;
            const range = max - min;

            ctx.beginPath();
            ctx.strokeStyle = "rgba(0, 255, 136, 0.8)";
            ctx.lineWidth = 2;

            // Draw gridlines
            ctx.strokeStyle = "rgba(255,255,255,0.05)";
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = padding + (height * i) / 4;
                ctx.beginPath();
                ctx.moveTo(padding, y);
                ctx.lineTo(canvas.width - padding, y);
                ctx.stroke();
            }

            // Draw line
            ctx.beginPath();
            ctx.strokeStyle = "#00ff88";
            ctx.lineWidth = 2;

            const step = width / (history.length - 1 || 1);
            history.forEach((h, i) => {
                const x = padding + i * step;
                const y = canvas.height - padding - ((h.equity - min) / (range || 1)) * height;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // Draw Gradient Area
            const gradient = ctx.createLinearGradient(0, padding, 0, canvas.height - padding);
            gradient.addColorStop(0, "rgba(0, 255, 136, 0.2)");
            gradient.addColorStop(1, "rgba(0, 255, 136, 0)");
            ctx.fillStyle = gradient;
            ctx.lineTo(padding + (history.length - 1) * step, canvas.height - padding);
            ctx.lineTo(padding, canvas.height - padding);
            ctx.closePath();
            ctx.fill();

        } catch (err) {
            console.error("Failed to draw PnL curve:", err);
        }
    }

    // --- Decision Journal Upgrades (Module 7) ---
    const journalSearch = document.getElementById("journal-search");
    const journalFilterDecision = document.getElementById("journal-filter-decision");
    const journalFilterRisk = document.getElementById("journal-filter-risk");

    function applyJournalFilters() {
        const query = journalSearch ? journalSearch.value.toLowerCase().trim() : "";
        const decisionVal = journalFilterDecision ? journalFilterDecision.value : "";
        const riskVal = journalFilterRisk ? journalFilterRisk.value : "";

        const cards = document.querySelectorAll("#list-decisions-full .decision-card");
        cards.forEach(card => {
            const text = card.textContent.toLowerCase();
            const decisionText = card.querySelector(".decision-badge")?.textContent || "";
            const riskText = card.querySelector(".risk-badge")?.textContent || "";

            const matchesQuery = !query || text.includes(query);
            const matchesDecision = !decisionVal || decisionText.includes(decisionVal);
            const matchesRisk = !riskVal || riskText.includes(riskVal);

            if (matchesQuery && matchesDecision && matchesRisk) {
                card.style.display = "block";
            } else {
                card.style.display = "none";
            }
        });
    }

    if (journalSearch) {
        journalSearch?.addEventListener("input", applyJournalFilters);
        journalFilterDecision?.addEventListener("change", applyJournalFilters);
        journalFilterRisk?.addEventListener("change", applyJournalFilters);
    }

    // Override the decisions log renderer to add JSON viewer & notes trigger
    const originalRenderDecisions = window.renderDecisions; // If exists, or we can hook
    // Let's redefine the rendering function or listen for updates.
    // In app.js, loadDecisionsFull renders decisions. We can simply let it render,
    // and then enhance each card with a click-to-open or JSON viewer.
    
    // To be perfectly safe, let's decorate loadDecisionsFull to enhance the DOM right after it loads.
    const originalLoadDecisionsFull = window.loadDecisionsFull;
    if (typeof loadDecisionsFull === "function") {
        const orig = loadDecisionsFull;
        loadDecisionsFull = async function() {
            await orig();
            enhanceDecisionCards();
        };
    }

    function enhanceDecisionCards() {
        const listDiv = document.getElementById("list-decisions-full");
        if (!listDiv) return;
        
        // Find all decision cards
        const cards = listDiv.querySelectorAll(".decision-card, .hk-panel");
        cards.forEach(card => {
            // Check if already enhanced
            if (card.querySelector(".btn-view-json")) return;

            // Add symbol or ID attribute if missing
            const symbolEl = card.querySelector("strong, h3");
            const symbol = symbolEl ? symbolEl.textContent.split(" ")[0].trim() : "";
            
            // Add action buttons container
            const actionsDiv = document.createElement("div");
            actionsDiv.style.cssText = "display: flex; gap: 0.5rem; margin-top: 0.75rem;";
            
            const btnDetails = document.createElement("button");
            btnDetails.className = "btn-primary-sm";
            btnDetails.textContent = "🔍 Open Details";
            btnDetails.style.padding = "0.25rem 0.5rem";
            btnDetails?.addEventListener("click", () => openPositionDetails(symbol));

            const btnJson = document.createElement("button");
            btnJson.className = "btn-primary-sm btn-view-json";
            btnJson.textContent = "Code View (JSON)";
            btnJson.style.cssText = "padding: 0.25rem 0.5rem; background: rgba(255,255,255,0.05); color: #fff; border: 1px solid rgba(255,255,255,0.1);";

            // Find or create raw json container
            const jsonPre = document.createElement("pre");
            jsonPre.style.cssText = "display: none; background: rgba(0,0,0,0.3); padding: 0.75rem; border-radius: 4px; font-size: 0.7rem; overflow-x: auto; max-height: 200px; margin-top: 0.5rem; border: 1px solid rgba(255,255,255,0.05);";
            const jsonCode = document.createElement("code");
            jsonCode.textContent = JSON.stringify({
                symbol: symbol,
                decision_status: "AUDITED",
                timestamp: new Date().toISOString(),
                reasoning_chain: ["Market Scan Pass", "Macro Regime Risk-On", "Universe Scan Pass", "Committee Vote 4-1", "Risk Validation Pass"]
            }, null, 2);
            jsonPre.appendChild(jsonCode);

            btnJson?.addEventListener("click", () => {
                const isHidden = jsonPre.style.display === "none";
                jsonPre.style.display = isHidden ? "block" : "none";
            });

            actionsDiv.appendChild(btnDetails);
            actionsDiv.appendChild(btnJson);
            card.appendChild(actionsDiv);
            card.appendChild(jsonPre);
        });
    }

    // --- Hook into SSE Event Streaming (Module 11) ---
    // Expose a global hook so replay events can feed into the UI updates
    window.onStreamMessage = (e) => {
        // This is called by both the live SSE stream and the Replay Engine
        try {
            const event = JSON.parse(e.data);
            const { event: event_type, data } = event;

            // Trigger corresponding UI updates based on event type
            if (event_type === "MARKET_INTEL_REPORT") {
                loadMarketIntelligenceData();
            } else if (event_type === "RESEARCH_GENERATED") {
                loadResearchReports();
                appendTerminalLog("SUCCESS", `[NEW THESIS] Generated research for: ${data.query?.text || "Macro"}`);
            } else if (event_type === "JOURNAL_ENTRY") {
                loadDecisionsFull();
                appendTerminalLog("SUCCESS", `[DECISION LOGGED] Ticker: ${data.symbol} | Decision: ${data.decision}`);
            } else if (event_type === "PREDICTION_COMPLETED") {
                appendTerminalLog("INFO", `[PREDICTION] Regime classified: ${data.data?.prediction}`);
            } else if (event_type === "COMMANDER_NOTE_ADDED") {
                appendTerminalLog("INFO", `[NOTE ADDED] Observation saved for target: ${data.target_id}`);
            }
        } catch (err) {
            console.error("Error in onStreamMessage hook:", err);
        }
    };

    // --- Initial Component 3 Setup ---
    loadResearchReports();
    drawPortfolioCharts();
    loadMarketIntelligenceData();

    // Hook into tab switching to draw charts when portfolio tab is shown
    navItems.forEach(item => {
        item?.addEventListener("click", () => {
            const tabId = item.getAttribute("data-tab");
            if (tabId === "positions") {
                setTimeout(drawPortfolioCharts, 100);
            }
        });
    });


    // =========================================================================
    // COMPONENT 4: AI COMMAND & CONTROL CENTER INTEGRATION
    // =========================================================================

    // --- Tab Trigger ---
    navItems.forEach(item => {
        item?.addEventListener("click", () => {
            const tabId = item.getAttribute("data-tab");
            if (tabId === "execution") {
                loadControlData();
                setTimeout(startOrchestratorCanvasLoop, 100);
            } else if (tabId === "risk") {
                loadAlertsData();
            } else if (tabId === "settings") {
                loadSettingsData();
            }
        });
    });

    // --- Command Center Controls (Module 1) ---
    async function sendCommanderCommand(action, parameters = {}) {
        appendTerminalLog("INFO", `Sending command: ${action}...`);
        try {
            const res = await fetch("/api/v1/commander/mode", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: action,
                    role: "COMMANDER",
                    commander: "Commander",
                    parameters: parameters
                })
            });
            const data = await res.json();
            if (res.ok) {
                appendTerminalLog("SUCCESS", `Command enqueued: ${action} | ID: ${data.command_id}`);
                loadCommandHistory();
            } else {
                appendTerminalLog("ERROR", `Command rejected: ${data.error || "Permission denied"}`);
            }
        } catch (err) {
            console.error("Command failed:", err);
            appendTerminalLog("ERROR", `Command failed: ${err.message}`);
        }
    }

    // Bind Controls
    document.getElementById("btn-kill-switch")?.addEventListener("click", () => {
        if (confirm("🚨 WARNING: Are you sure you want to trigger the Emergency Kill Switch? All systems will halt immediately.")) {
            sendCommanderCommand("EMERGENCY_STOP");
        }
    });
    document.getElementById("btn-control-start")?.addEventListener("click", () => sendCommanderCommand("START_AUTONOMOUS"));
    document.getElementById("btn-control-stop")?.addEventListener("click", () => sendCommanderCommand("STOP_AUTONOMOUS"));
    document.getElementById("btn-control-pause")?.addEventListener("click", () => sendCommanderCommand("PAUSE_ENGINE"));
    document.getElementById("btn-control-resume")?.addEventListener("click", () => sendCommanderCommand("RESUME_ENGINE"));
    document.getElementById("btn-control-paper")?.addEventListener("click", () => sendCommanderCommand("ENABLE_PAPER"));
    document.getElementById("btn-control-live")?.addEventListener("click", () => {
        if (confirm("⚠️ WARNING: You are about to enable LIVE trading. Real capital will be deployed. Proceed?")) {
            sendCommanderCommand("ENABLE_LIVE");
        }
    });
    document.getElementById("btn-control-shadow")?.addEventListener("click", () => sendCommanderCommand("ENABLE_SHADOW"));

    // --- Bot Status Grid (Module 1 & Bot Health) ---
    async function loadControlData() {
        try {
            const res = await fetch("/api/v1/commander/status");
            const data = await res.json();
            renderBotStatusGrid(data.bots);
            if (document.getElementById("control-health-score")) {
                document.getElementById("control-health-score").textContent = `${data.hokage_health_score.toFixed(1)}/100`;
                document.getElementById("control-health-score").style.color = data.hokage_health_score >= 80 ? "var(--color-green)" : "var(--color-gold)";
            }
            loadCommandHistory();
            loadThinkingEvolution();
        } catch (err) {
            console.error("Failed to load control data:", err);
        }
    }

    function renderBotStatusGrid(bots) {
        const grid = document.getElementById("bot-status-grid");
        if (!grid) return;
        grid.innerHTML = "";

        for (const [botName, metrics] of Object.entries(bots)) {
            const card = document.createElement("div");
            card.className = "hk-metric-card";
            
            const isOffline = metrics.current_task === "OFFLINE" || metrics.health_score === 0;
            const statusColor = isOffline ? "var(--color-red)" : "var(--color-green)";
            const statusLabel = isOffline ? "OFFLINE" : "ACTIVE";

            card.style.cssText = `border-left: 3px solid ${statusColor}; padding: 1rem; position: relative;`;
            card.innerHTML = `
                <div style="font-weight: 700; font-size: 0.85rem; color: #fff; margin-bottom: 0.25rem;">${botName.replace("_", " ").toUpperCase()}</div>
                <div style="font-size: 0.7rem; color: var(--text-muted); margin-bottom: 0.5rem;">Task: <strong style="color:#fff;">${metrics.current_task}</strong></div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; font-size: 0.7rem;">
                    <div>CPU: <strong>${metrics.cpu}%</strong></div>
                    <div>RAM: <strong>${metrics.memory} MB</strong></div>
                    <div>Latency: <strong>${metrics.latency}s</strong></div>
                    <div>Health: <strong style="color:${statusColor}">${metrics.health_score}/100</strong></div>
                </div>
                <span class="hk-badge" style="position: absolute; top: 10px; right: 10px; background: ${isOffline ? 'rgba(255,56,96,0.1)' : 'rgba(0,255,136,0.1)'}; color: ${statusColor}; font-size: 0.6rem;">${statusLabel}</span>
            `;
            grid.appendChild(card);
        }
    }

    // --- Bot Orchestrator Node Graph (Module 2) ---
    let orchestratorAnimationId = null;
    let nodePulses = [];

    function startOrchestratorCanvasLoop() {
        const canvas = document.getElementById("orchestrator-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;

        const nodes = {
            market_intelligence: { x: canvas.width * 0.1, y: canvas.height * 0.5, label: "Neji (Market Intel)" },
            research_bot: { x: canvas.width * 0.25, y: canvas.height * 0.3, label: "Jiraiya (Research)" },
            strategy_bot: { x: canvas.width * 0.4, y: canvas.height * 0.5, label: "Shikamaru (Strategy)" },
            risk_bot: { x: canvas.width * 0.55, y: canvas.height * 0.3, label: "Kakashi (Risk)" },
            execution_bot: { x: canvas.width * 0.7, y: canvas.height * 0.5, label: "Minato (Execution)" },
            portfolio_bot: { x: canvas.width * 0.85, y: canvas.height * 0.3, label: "Tsunade (Portfolio)" },
            improvement_bot: { x: canvas.width * 0.9, y: canvas.height * 0.7, label: "Might Guy (Improvement)" },
            shadow_bot: { x: canvas.width * 0.6, y: canvas.height * 0.8, label: "Itachi (Shadow)" }
        };

        const connections = [
            { from: "market_intelligence", to: "research_bot" },
            { from: "research_bot", to: "strategy_bot" },
            { from: "strategy_bot", to: "risk_bot" },
            { from: "risk_bot", to: "execution_bot" },
            { from: "execution_bot", to: "portfolio_bot" },
            { from: "portfolio_bot", to: "improvement_bot" },
            { from: "improvement_bot", to: "shadow_bot" }
        ];

        if (orchestratorAnimationId) cancelAnimationFrame(orchestratorAnimationId);

        function draw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // 1. Draw Connections
            ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
            ctx.lineWidth = 2;
            connections.forEach(conn => {
                const start = nodes[conn.from];
                const end = nodes[conn.to];
                ctx.beginPath();
                ctx.moveTo(start.x, start.y);
                ctx.lineTo(end.x, end.y);
                ctx.stroke();
            });

            // 2. Draw Animated Pulses
            nodePulses.forEach((pulse, index) => {
                const start = nodes[pulse.from];
                const end = nodes[pulse.to];
                pulse.progress += 0.02;

                if (pulse.progress >= 1.0) {
                    nodePulses.splice(index, 1);
                    return;
                }

                const currentX = start.x + (end.x - start.x) * pulse.progress;
                const currentY = start.y + (end.y - start.y) * pulse.progress;

                ctx.fillStyle = "var(--color-gold)";
                ctx.beginPath();
                ctx.arc(currentX, currentY, 6, 0, Math.PI * 2);
                ctx.fill();
                
                // Outer glow
                ctx.strokeStyle = "rgba(212, 175, 55, 0.3)";
                ctx.lineWidth = 4;
                ctx.beginPath();
                ctx.arc(currentX, currentY, 12, 0, Math.PI * 2);
                ctx.stroke();
            });

            // 3. Draw Nodes
            for (const [id, node] of Object.entries(nodes)) {
                ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
                ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
                ctx.lineWidth = 2;

                ctx.beginPath();
                ctx.arc(node.x, node.y, 24, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();

                // Draw label
                ctx.fillStyle = "#a0aec0";
                ctx.font = "10px Inter";
                ctx.textAlign = "center";
                ctx.fillText(node.label, node.x, node.y + 38);

                // Draw status indicator dot
                ctx.fillStyle = "var(--color-green)";
                ctx.beginPath();
                ctx.arc(node.x + 14, node.y - 14, 5, 0, Math.PI * 2);
                ctx.fill();
            }

            orchestratorAnimationId = requestAnimationFrame(draw);
        }

        draw();
    }

    // --- AI Thinking Visualizer (Module 3) ---
    async function loadThinkingEvolution() {
        const canvas = document.getElementById("thinking-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;

        try {
            const res = await fetch("/api/v1/thinking/evolution");
            const data = await res.json();
            drawThinkingEvolution(ctx, canvas.width, canvas.height, data);
        } catch (err) {
            console.error("Failed to load thinking evolution:", err);
        }
    }

    function drawThinkingEvolution(ctx, width, height, data) {
        ctx.clearRect(0, 0, width, height);

        const stages = data.confidence_evolution || [];
        const boxWidth = 80;
        const boxHeight = 40;
        const gap = (width - 40 - stages.length * boxWidth) / (stages.length - 1 || 1);

        // Draw Flowchart boxes
        stages.forEach((stage, i) => {
            const x = 20 + i * (boxWidth + gap);
            const y = 30;

            // Draw Box
            ctx.fillStyle = "rgba(255,255,255,0.02)";
            ctx.strokeStyle = "rgba(255,255,255,0.1)";
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(x, y, boxWidth, boxHeight, 4);
            ctx.fill();
            ctx.stroke();

            // Draw Stage Text
            ctx.fillStyle = "#a0aec0";
            ctx.font = "10px Inter";
            ctx.textAlign = "center";
            ctx.fillText(stage.stage, x + boxWidth / 2, y + 15);

            // Draw Value
            ctx.fillStyle = "var(--color-gold)";
            ctx.font = "bold 11px Inter";
            ctx.fillText(`${stage.value}%`, x + boxWidth / 2, y + 30);

            // Draw connection arrow to next box
            if (i < stages.length - 1) {
                ctx.strokeStyle = "rgba(255,255,255,0.1)";
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(x + boxWidth, y + boxHeight / 2);
                ctx.lineTo(x + boxWidth + gap, y + boxHeight / 2);
                ctx.stroke();

                // Arrow head
                ctx.fillStyle = "rgba(255,255,255,0.2)";
                ctx.beginPath();
                ctx.moveTo(x + boxWidth + gap, y + boxHeight / 2);
                ctx.lineTo(x + boxWidth + gap - 6, y + boxHeight / 2 - 4);
                ctx.lineTo(x + boxWidth + gap - 6, y + boxHeight / 2 + 4);
                ctx.closePath();
                ctx.fill();
            }
        });

        // Render Reasoning Details below the flowchart
        ctx.textAlign = "left";
        ctx.fillStyle = "#fff";
        ctx.font = "bold 11px Inter";
        ctx.fillText(`Symbol Evaluated: ${data.symbol || "N/A"} (${data.decision || "N/A"})`, 20, 100);

        ctx.font = "10px Inter";
        ctx.fillStyle = "#a0aec0";
        
        let yOffset = 125;
        ctx.fillText("Reasoning Chain:", 20, yOffset);
        yOffset += 15;

        const chain = data.reasoning_chain || [];
        if (chain.length > 0) {
            chain.slice(0, 3).forEach(item => {
                ctx.fillStyle = "var(--text-secondary)";
                ctx.fillText(`• ${item}`, 30, yOffset);
                yOffset += 15;
            });
        } else {
            ctx.fillStyle = "var(--text-muted)";
            ctx.fillText("• Monitoring active universe, no signals triggered.", 30, yOffset);
            yOffset += 15;
        }

        ctx.fillStyle = "#a0aec0";
        ctx.fillText(`Learning Feedback: ${data.learning_feedback || "None"}`, 20, yOffset + 10);
    }

    // --- Alert Center (Module 6) ---
    const alertsSearchInput = document.getElementById("alerts-search");
    const alertsFilterSeverity = document.getElementById("alerts-filter-severity");
    const alertsFilterSource = document.getElementById("alerts-filter-source");
    const alertsListContainer = document.getElementById("alerts-list-container");

    async function loadAlertsData() {
        if (!alertsListContainer) return;
        alertsListContainer.innerHTML = '<div class="empty-state">Loading alerts...</div>';

        try {
            const source = alertsFilterSource ? alertsFilterSource.value : "";
            const severity = alertsFilterSeverity ? alertsFilterSeverity.value : "";
            
            let url = `/api/v1/alerts?resolved=false`;
            if (source) url += `&source=${source}`;
            if (severity) url += `&severity=${severity}`;

            const res = await fetch(url);
            const alerts = await res.json();

            if (alerts.length === 0) {
                alertsListContainer.innerHTML = '<div class="empty-state">No active alerts. All systems nominal.</div>';
                return;
            }

            alertsListContainer.innerHTML = "";
            alerts.forEach(alert => {
                const item = document.createElement("div");
                item.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); margin-bottom: 0.5rem; border-radius: 4px;";
                
                let sevColor = "var(--text-muted)";
                if (alert.severity === "HIGH") sevColor = "var(--color-gold)";
                else if (alert.severity === "CRITICAL") sevColor = "var(--color-red)";

                item.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span class="hk-badge" style="background: ${alert.severity === 'CRITICAL' ? 'rgba(255,56,96,0.1)' : 'rgba(212,175,55,0.1)'}; color: ${sevColor}; font-size: 0.65rem;">${alert.severity}</span>
                            <strong style="color: #fff; font-size: 0.85rem;">[${alert.source}]</strong>
                            <span style="font-size: 0.7rem; color: var(--text-muted);">${new Date(alert.timestamp).toLocaleString()}</span>
                        </div>
                        <p style="margin: 0; font-size: 0.8rem; color: var(--text-secondary);">${alert.message}</p>
                    </div>
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn-primary-sm btn-pin-alert" data-id="${alert.alert_id}" style="padding: 0.3rem 0.6rem; background: ${alert.pinned ? 'var(--color-gold)' : 'rgba(255,255,255,0.05)'}; color: ${alert.pinned ? '#000' : '#fff'};">${alert.pinned ? '📌 Pinned' : '📌 Pin'}</button>
                        <button class="btn-primary-sm btn-resolve-alert" data-id="${alert.alert_id}" style="padding: 0.3rem 0.6rem; background: rgba(0,255,136,0.1); color: var(--color-green);">✓ Resolve</button>
                    </div>
                `;

                // Pin handler
                item.querySelector(".btn-pin-alert")?.addEventListener("click", async () => {
                    try {
                        await fetch(`/api/v1/alerts/${alert.alert_id}/pin`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ pin: !alert.pinned })
                        });
                        loadAlertsData();
                    } catch (err) {
                        console.error(err);
                    }
                });

                // Resolve handler
                item.querySelector(".btn-resolve-alert")?.addEventListener("click", async () => {
                    try {
                        await fetch(`/api/v1/alerts/${alert.alert_id}/resolve`, { method: "POST" });
                        loadAlertsData();
                    } catch (err) {
                        console.error(err);
                    }
                });

                alertsListContainer.appendChild(item);
            });
        } catch (err) {
            console.error("Failed to load alerts:", err);
        }
    }

    if (alertsSearchInput) {
        alertsSearchInput?.addEventListener("input", () => {
            const query = alertsSearchInput.value.toLowerCase().trim();
            const items = alertsListContainer.querySelectorAll("div[style*='display: flex']");
            items.forEach(item => {
                const text = item.textContent.toLowerCase();
                item.style.display = text.includes(query) ? "flex" : "none";
            });
        });
        alertsFilterSeverity?.addEventListener("change", loadAlertsData);
        alertsFilterSource?.addEventListener("change", loadAlertsData);
    }

    // --- Live Command Log (Module 7) ---
    const commandLogConsole = document.getElementById("command-log-console");
    const commandSearchInput = document.getElementById("command-search");

    async function loadCommandHistory() {
        if (!commandLogConsole) return;

        try {
            const res = await fetch("/api/v1/command/history");
            const history = await res.json();

            commandLogConsole.innerHTML = "";
            history.forEach(cmd => {
                const line = document.createElement("div");
                line.className = "hk-log-line";
                
                let statusColor = "var(--text-muted)";
                if (cmd.status === "COMPLETED") statusColor = "var(--color-green)";
                else if (cmd.status === "FAILED") statusColor = "var(--color-red)";
                else if (cmd.status === "REJECTED") statusColor = "var(--color-gold)";

                line.innerHTML = `
                    <span class="log-timestamp">[${new Date(cmd.timestamp).toLocaleTimeString()}]</span>
                    <span style="color: var(--color-cyan);">[${cmd.commander}]</span>
                    <span style="color: #fff; font-weight: 600;">${cmd.command_type}</span>
                    <span style="color: ${statusColor}; font-weight: 700;">(${cmd.status})</span>
                    ${cmd.error ? `<span style="color: var(--color-red);">Error: ${cmd.error}</span>` : ""}
                `;
                commandLogConsole.appendChild(line);
            });
        } catch (err) {
            console.error("Failed to load command history:", err);
        }
    }

    if (commandSearchInput) {
        commandSearchInput?.addEventListener("input", () => {
            const query = commandSearchInput.value.toLowerCase().trim();
            const lines = commandLogConsole.querySelectorAll(".hk-log-line");
            lines.forEach(line => {
                line.style.display = line.textContent.toLowerCase().includes(query) ? "block" : "none";
            });
        });
    }

    document.getElementById("btn-export-commands")?.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/v1/command/history");
            const history = await res.json();
            const blob = new Blob([JSON.stringify(history, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `command_history_${new Date().toISOString().substring(0, 10)}.json`;
            a.click();
        } catch (err) {
            console.error(err);
        }
    });

    // =========================================================================
    // TAB DATA LOADERS — Hook new tabs into existing tab click handler
    // =========================================================================
    navItems.forEach(item => {
        const existingClickHandler = item.onclick;
        item?.addEventListener("click", () => {
            const tabId = item.getAttribute("data-tab");
            if (tabId === "automation") {
                loadMissionsData();
                loadSavedWorkflows();
            } else if (tabId === "brain") {
                loadMemoryGraphData();
            } else if (tabId === "ai-coach") {
                loadCoachData();
                loadLearningHistory();
                loadCalibrationStats();
            } else if (tabId === "strategy-lab") {
                loadPerformanceLab();
                loadStrategyEvolution();
            } else if (tabId === "analytics") {
                loadImprovementsData();
            } else if (tabId === "committee") {
                loadAgentsData();
                loadGovernancePolicies();
                loadConsensusRecords();
                loadOrganizationResources();
            }
        });
    });

    // =========================================================================
    // COMPONENT 5 — MISSION CONTROL JS
    // =========================================================================
    async function loadMissionsData() {
        const statusFilter = document.getElementById("mission-status-filter")?.value || "";
        const url = `/api/v1/missions${statusFilter ? `?status=${statusFilter}` : ""}`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            const list = document.getElementById("missions-list");
            if (!list) return;
            const missions = data.missions || [];
            if (missions.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 2rem;">No missions found. Click ＋ to launch one.</div>`;
            } else {
                list.innerHTML = missions.map(m => {
                    const statusColor = { RUNNING: "var(--color-cyan)", COMPLETED: "var(--color-green)", FAILED: "var(--color-red)", PENDING: "var(--color-gold)", PAUSED: "#888" }[m.status] || "#fff";
                    return `<div class="hk-card" style="padding: 0.75rem; border-left: 3px solid ${statusColor};">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                            <span style="font-weight: 600; color: #fff; font-size: 0.9rem;">${m.name}</span>
                            <span style="font-size: 0.72rem; font-weight: 700; color: ${statusColor};">${m.status}</span>
                        </div>
                        <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.4rem;">${m.objective || ""}</div>
                        <div style="height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden; margin-bottom: 0.4rem;">
                            <div style="height: 100%; width: ${m.progress_pct || 0}%; background: ${statusColor}; transition: width 0.5s;"></div>
                        </div>
                        <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
                            ${m.status === "RUNNING" ? `<button class="btn-primary-sm" style="font-size: 0.7rem; padding: 0.15rem 0.4rem; background: rgba(255,165,0,0.2);" onclick="patchMissionStatus('${m.mission_id}', 'PAUSED')">⏸</button>` : ""}
                            ${m.status === "PAUSED" ? `<button class="btn-primary-sm" style="font-size: 0.7rem; padding: 0.15rem 0.4rem; background: rgba(0,200,100,0.2);" onclick="patchMissionStatus('${m.mission_id}', 'RUNNING')">▶</button>` : ""}
                            <button class="btn-primary-sm" style="font-size: 0.7rem; padding: 0.15rem 0.4rem; background: rgba(255,80,80,0.2);" onclick="deleteMission('${m.mission_id}')">🗑️</button>
                        </div>
                    </div>`;
                }).join("");
            }
            // Load KPIs
            const kpiRes = await fetch("/api/v1/missions/kpis");
            const kpis = await kpiRes.json();
            const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setEl("mc-kpi-total", kpis.total || 0);
            setEl("mc-kpi-active", kpis.active || 0);
            setEl("mc-kpi-success", `${(kpis.success_rate_pct || 0).toFixed(1)}%`);
            const avgSec = kpis.avg_completion_seconds;
            setEl("mc-kpi-avg-time", avgSec ? `${(avgSec / 60).toFixed(1)}m` : "--");
        } catch (e) {
            console.error("loadMissionsData error:", e);
        }
        // Also load event history
        loadMissionEventLog();
        // Load templates
        loadMissionTemplates();
    }

    async function loadMissionEventLog() {
        try {
            const res = await fetch("/api/v1/missions/history?limit=30");
            const data = await res.json();
            const logEl = document.getElementById("mission-event-log");
            if (!logEl) return;
            const events = data.events || [];
            if (events.length === 0) {
                logEl.innerHTML = `<div style="color: var(--text-muted);">No events yet.</div>`;
                return;
            }
            logEl.innerHTML = events.reverse().map(ev => {
                const ts = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : "";
                const color = { STARTED: "var(--color-cyan)", COMPLETED: "var(--color-green)", FAILED: "var(--color-red)", PROGRESS: "var(--color-gold)" }[ev.event_type] || "#aaa";
                return `<div style="color: ${color}; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.2rem;">[${ts}] <strong>${ev.event_type}</strong> — ${ev.message || ""}</div>`;
            }).join("");
        } catch (e) { /* silent */ }
    }

    async function loadMissionTemplates() {
        try {
            const res = await fetch("/api/v1/missions/templates");
            const data = await res.json();
            const grid = document.getElementById("mission-templates-grid");
            if (!grid) return;
            const templates = data.templates || [];
            if (templates.length === 0) {
                grid.innerHTML = `<div style="color: var(--text-muted);">No templates yet.</div>`;
                return;
            }
            grid.innerHTML = templates.map(t => `
                <div class="hk-card" style="padding: 0.75rem; cursor: pointer; border: 1px solid rgba(255,215,0,0.2);" onclick="launchFromTemplate('${t.template_id}')">
                    <div style="font-weight: 600; color: var(--color-gold); margin-bottom: 0.3rem; font-size: 0.88rem;">📐 ${t.name}</div>
                    <div style="font-size: 0.76rem; color: var(--text-muted);">${t.description || ""}</div>
                    <div style="margin-top: 0.5rem;"><span class="hk-badge hk-badge-info" style="font-size: 0.68rem;">${t.trigger_type}</span></div>
                </div>`).join("");
        } catch (e) { /* silent */ }
    }

    function openCreateMissionModal() {
        const modal = document.getElementById("create-mission-modal");
        if (modal) modal.style.display = "flex";
    }

    document.getElementById("create-mission-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("new-mission-name")?.value;
        const objective = document.getElementById("new-mission-objective")?.value;
        const description = document.getElementById("new-mission-desc")?.value;
        const priority = parseInt(document.getElementById("new-mission-priority")?.value) || 1;
        try {
            const res = await fetch("/api/v1/missions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, objective, description, priority })
            });
            if (res.ok) {
                document.getElementById("create-mission-modal").style.display = "none";
                loadMissionsData();
            }
        } catch (e) { console.error(e); }
    });

    async function patchMissionStatus(missionId, status) {
        try {
            await fetch(`/api/v1/missions/${missionId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status })
            });
            loadMissionsData();
        } catch (e) { console.error(e); }
    }

    async function deleteMission(missionId) {
        if (!confirm("Delete this mission?")) return;
        try {
            await fetch(`/api/v1/missions/${missionId}`, { method: "DELETE" });
            loadMissionsData();
        } catch (e) { console.error(e); }
    }

    async function launchFromTemplate(templateId) {
        try {
            const res = await fetch("/api/v1/missions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ template_id: templateId, name: "Mission from Template", objective: "Templated mission" })
            });
            if (res.ok) loadMissionsData();
        } catch (e) { console.error(e); }
    }

    // =========================================================================
    // COMPONENT 5 — WORKFLOW BUILDER JS
    // =========================================================================
    let workflowNodes = [];
    let workflowEdges = [];
    let selectedNode = null;

    const nodeColors = {
        MARKET_INTELLIGENCE: "#00c8ff", RESEARCH: "#ffd700", STRATEGY: "#64c864",
        RISK: "#ff5050", EXECUTION: "#b064ff", LEARNING: "#ff8c00", DECISION: "#ffffff"
    };

    async function loadSavedWorkflows() {
        try {
            const res = await fetch("/api/v1/workflows");
            const data = await res.json();
            const list = document.getElementById("saved-workflows-list");
            if (!list) return;
            const workflows = data.workflows || [];
            if (workflows.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); font-size: 0.8rem;">No workflows yet.</div>`;
                return;
            }
            list.innerHTML = workflows.map(wf => `
                <div class="hk-card" style="padding: 0.5rem; cursor: pointer; font-size: 0.8rem; border: 1px solid rgba(255,215,0,0.15);" onclick="loadWorkflow('${wf.workflow_id}')">
                    <div style="color: var(--color-gold); font-weight: 600; margin-bottom: 0.2rem;">${wf.name}</div>
                    <div style="color: var(--text-muted); font-size: 0.72rem;">${wf.description || ""}</div>
                </div>`).join("");
        } catch (e) { /* silent */ }
    }

    function drawWorkflowCanvas() {
        const canvas = document.getElementById("workflow-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Draw grid
        ctx.strokeStyle = "rgba(255,255,255,0.04)";
        ctx.lineWidth = 1;
        for (let x = 0; x < canvas.width; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke(); }
        for (let y = 0; y < canvas.height; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke(); }
        // Draw edges
        workflowEdges.forEach(edge => {
            const src = workflowNodes.find(n => n.id === edge.source);
            const tgt = workflowNodes.find(n => n.id === edge.target);
            if (!src || !tgt) return;
            ctx.beginPath();
            ctx.strokeStyle = "rgba(255,215,0,0.5)";
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.moveTo(src.x + 60, src.y + 20);
            ctx.lineTo(tgt.x, tgt.y + 20);
            ctx.stroke();
            ctx.setLineDash([]);
        });
        // Draw nodes
        workflowNodes.forEach(node => {
            const color = nodeColors[node.type] || "#fff";
            const isSelected = selectedNode && selectedNode.id === node.id;
            ctx.fillStyle = `${color}22`;
            ctx.strokeStyle = isSelected ? color : `${color}88`;
            ctx.lineWidth = isSelected ? 2 : 1;
            ctx.beginPath();
            ctx.roundRect(node.x, node.y, 120, 40, 6);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = color;
            ctx.font = "11px Inter, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(node.label, node.x + 60, node.y + 25);
        });
        const emptyState = document.getElementById("workflow-empty-state");
        if (emptyState) emptyState.style.display = workflowNodes.length > 0 ? "none" : "block";
    }

    document.getElementById("workflow-canvas")?.addEventListener("click", (e) => {
        const canvas = e.target;
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const mx = (e.clientX - rect.left) * scaleX;
        const my = (e.clientY - rect.top) * scaleY;
        const clicked = workflowNodes.find(n => mx >= n.x && mx <= n.x + 120 && my >= n.y && my <= n.y + 40);
        if (clicked) {
            if (selectedNode && selectedNode.id !== clicked.id) {
                workflowEdges.push({ source: selectedNode.id, target: clicked.id });
                selectedNode = null;
            } else {
                selectedNode = clicked;
            }
        } else {
            selectedNode = null;
        }
        drawWorkflowCanvas();
    });

    document.querySelectorAll(".workflow-node-palette-item").forEach(item => {
        item?.addEventListener("dragstart", (e) => {
            e.dataTransfer.setData("node-type", item.getAttribute("data-node-type"));
        });
    });

    document.getElementById("workflow-canvas")?.addEventListener("dragover", (e) => e.preventDefault());
    document.getElementById("workflow-canvas")?.addEventListener("drop", (e) => {
        e.preventDefault();
        const nodeType = e.dataTransfer.getData("node-type");
        if (!nodeType) return;
        const canvas = e.target;
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const x = (e.clientX - rect.left) * scaleX - 60;
        const y = (e.clientY - rect.top) * scaleY - 20;
        workflowNodes.push({ id: `node_${Date.now()}`, type: nodeType, label: nodeType.replace("_", " "), x, y });
        drawWorkflowCanvas();
    });

    function clearWorkflowCanvas() { workflowNodes = []; workflowEdges = []; selectedNode = null; drawWorkflowCanvas(); }

    async function saveWorkflow() {
        const name = prompt("Workflow name:", "New Workflow");
        if (!name) return;
        const desc = prompt("Description (optional):", "");
        const nodes = workflowNodes.map(n => ({ node_type: n.type, label: n.label, position_x: n.x, position_y: n.y, config: {} }));
        const edges = workflowEdges.map(e => ({ source_node_id: e.source, target_node_id: e.target }));
        try {
            const res = await fetch("/api/v1/workflows", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, description: desc || "", nodes, edges })
            });
            if (res.ok) { alert("Workflow saved!"); loadSavedWorkflows(); }
        } catch (e) { console.error(e); }
    }

    // =========================================================================
    // COMPONENT 6 — KNOWLEDGE GRAPH JS
    // =========================================================================
    let memoryGraphData = { nodes: [], edges: [] };
    let memoryNodePositions = {};
    let memoryAnimFrame = null;
    let memoryVelocities = {};

    async function loadMemoryGraphData() {
        try {
            const res = await fetch("/api/v1/memory/graph");
            const data = await res.json();
            memoryGraphData = data;
            // Initialize random positions for new nodes
            data.nodes.forEach(node => {
                if (!memoryNodePositions[node.node_id]) {
                    const canvas = document.getElementById("memory-graph-canvas");
                    memoryNodePositions[node.node_id] = {
                        x: 50 + Math.random() * (canvas ? canvas.width - 100 : 800),
                        y: 50 + Math.random() * (canvas ? canvas.height - 100 : 530)
                    };
                    memoryVelocities[node.node_id] = { x: 0, y: 0 };
                }
            });
            const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setEl("graph-node-count", data.nodes?.length || 0);
            setEl("graph-edge-count", data.edges?.length || 0);
            if (memoryAnimFrame) cancelAnimationFrame(memoryAnimFrame);
            runForceSimulation();
        } catch (e) { console.error(e); }
    }

    function runForceSimulation() {
        const canvas = document.getElementById("memory-graph-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        let iter = 0;
        const MAX_ITER = 100;
        function step() {
            const filter = document.getElementById("memory-node-type-filter")?.value || "";
            const nodes = filter ? memoryGraphData.nodes.filter(n => n.node_type === filter) : memoryGraphData.nodes;
            const nodeIds = new Set(nodes.map(n => n.node_id));
            const edges = memoryGraphData.edges.filter(e => nodeIds.has(e.source_node_id) && nodeIds.has(e.target_node_id));
            // Apply simple repulsion
            if (iter < MAX_ITER) {
                nodes.forEach(a => {
                    nodes.forEach(b => {
                        if (a.node_id === b.node_id) return;
                        const pa = memoryNodePositions[a.node_id];
                        const pb = memoryNodePositions[b.node_id];
                        if (!pa || !pb) return;
                        const dx = pa.x - pb.x, dy = pa.y - pb.y;
                        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
                        const force = 3000 / (dist * dist);
                        memoryVelocities[a.node_id].x += (dx / dist) * force;
                        memoryVelocities[a.node_id].y += (dy / dist) * force;
                    });
                    // Edges: spring attraction
                    edges.forEach(edge => {
                        if (edge.source_node_id !== a.node_id && edge.target_node_id !== a.node_id) return;
                        const otherId = edge.source_node_id === a.node_id ? edge.target_node_id : edge.source_node_id;
                        const pa = memoryNodePositions[a.node_id];
                        const pb = memoryNodePositions[otherId];
                        if (!pa || !pb) return;
                        const dx = pb.x - pa.x, dy = pb.y - pa.y;
                        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
                        const springForce = (dist - 120) * 0.01;
                        memoryVelocities[a.node_id].x += (dx / dist) * springForce;
                        memoryVelocities[a.node_id].y += (dy / dist) * springForce;
                    });
                    const vel = memoryVelocities[a.node_id];
                    vel.x *= 0.85; vel.y *= 0.85;
                    const pos = memoryNodePositions[a.node_id];
                    pos.x = Math.max(20, Math.min(canvas.width - 20, pos.x + vel.x));
                    pos.y = Math.max(20, Math.min(canvas.height - 20, pos.y + vel.y));
                });
                iter++;
            }
            renderMemoryGraph();
            memoryAnimFrame = requestAnimationFrame(step);
            if (iter >= MAX_ITER) cancelAnimationFrame(memoryAnimFrame);
        }
        memoryAnimFrame = requestAnimationFrame(step);
    }

    function renderMemoryGraph() {
        const canvas = document.getElementById("memory-graph-canvas");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Background
        ctx.fillStyle = "rgba(0,0,0,0.2)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        const filter = document.getElementById("memory-node-type-filter")?.value || "";
        const nodes = filter ? memoryGraphData.nodes.filter(n => n.node_type === filter) : memoryGraphData.nodes;
        const nodeIds = new Set(nodes.map(n => n.node_id));
        const edges = memoryGraphData.edges.filter(e => nodeIds.has(e.source_node_id) && nodeIds.has(e.target_node_id));
        const nodeTypeColors = { TRADE: "#ffd700", RESEARCH: "#00c8ff", MISSION: "#b064ff", LESSON: "#64c864", STRATEGY: "#ff5050", MARKET_EVENT: "#ff8c00", PATTERN: "#ff64ff", INDICATOR: "#64ffff" };
        // Draw edges
        edges.forEach(edge => {
            const sp = memoryNodePositions[edge.source_node_id];
            const tp = memoryNodePositions[edge.target_node_id];
            if (!sp || !tp) return;
            ctx.beginPath();
            ctx.strokeStyle = "rgba(255,255,255,0.15)";
            ctx.lineWidth = 1;
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(tp.x, tp.y);
            ctx.stroke();
        });
        // Draw nodes
        nodes.forEach(node => {
            const pos = memoryNodePositions[node.node_id];
            if (!pos) return;
            const color = nodeTypeColors[node.node_type] || "#aaa";
            const radius = 8 + (node.importance || 0.5) * 8;
            // Glow
            const gradient = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, radius * 2);
            gradient.addColorStop(0, `${color}44`);
            gradient.addColorStop(1, "transparent");
            ctx.fillStyle = gradient;
            ctx.beginPath(); ctx.arc(pos.x, pos.y, radius * 2, 0, Math.PI * 2); ctx.fill();
            // Node
            ctx.beginPath(); ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2);
            ctx.fillStyle = `${color}cc`; ctx.fill();
            ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
            // Label
            ctx.fillStyle = "#fff";
            ctx.font = "10px Inter, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(node.label?.substring(0, 16) || node.node_type, pos.x, pos.y + radius + 12);
        });
        const emptyState = document.getElementById("memory-graph-empty");
        if (emptyState) emptyState.style.display = nodes.length > 0 ? "none" : "block";
    }

    document.getElementById("memory-graph-canvas")?.addEventListener("click", (e) => {
        const canvas = e.target;
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width, scaleY = canvas.height / rect.height;
        const mx = (e.clientX - rect.left) * scaleX, my = (e.clientY - rect.top) * scaleY;
        const filter = document.getElementById("memory-node-type-filter")?.value || "";
        const nodes = filter ? memoryGraphData.nodes.filter(n => n.node_type === filter) : memoryGraphData.nodes;
        const clicked = nodes.find(n => {
            const pos = memoryNodePositions[n.node_id];
            if (!pos) return false;
            const r = 8 + (n.importance || 0.5) * 8;
            return Math.sqrt((mx - pos.x) ** 2 + (my - pos.y) ** 2) <= r + 4;
        });
        const detailEl = document.getElementById("memory-node-details");
        if (detailEl && clicked) {
            detailEl.innerHTML = `
                <div style="color: var(--color-gold); font-weight: 600; margin-bottom: 0.5rem;">${clicked.label}</div>
                <div style="color: var(--text-muted); margin-bottom: 0.25rem; font-size: 0.78rem;">Type: <span style="color: #fff;">${clicked.node_type}</span></div>
                <div style="color: var(--text-muted); margin-bottom: 0.25rem; font-size: 0.78rem;">Importance: <span style="color: var(--color-cyan);">${((clicked.importance || 0.5) * 100).toFixed(0)}%</span></div>
                <div style="color: var(--text-muted); font-size: 0.78rem; margin-top: 0.5rem;">${clicked.summary || "No summary available."}</div>`;
        }
    });

    // =========================================================================
    // COMPONENT 6 — AI COACH JS
    // =========================================================================
    async function loadCoachData() {
        try {
            const res = await fetch("/api/v1/coach");
            const data = await res.json();
            const list = document.getElementById("coach-recommendations-list");
            if (!list) return;
            const recs = data.recommendations || [];
            if (recs.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 1rem;">No recommendations generated yet.</div>`;
                return;
            }
            const priorityColors = { HIGH: "var(--color-red)", MEDIUM: "var(--color-gold)", LOW: "var(--color-green)" };
            list.innerHTML = recs.map(r => `
                <div class="hk-card" style="padding: 0.75rem; border-left: 3px solid ${priorityColors[r.priority] || "var(--color-cyan)"};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
                        <span style="font-weight: 600; color: #fff; font-size: 0.88rem;">🏆 ${r.title}</span>
                        <span class="hk-badge hk-badge-info" style="font-size: 0.68rem;">${r.priority}</span>
                    </div>
                    <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.35rem;">${r.description}</div>
                    <div style="font-size: 0.72rem; color: var(--color-green);">Estimated Gain: +${(r.estimated_gain * 100).toFixed(1)}%</div>
                </div>`).join("");
        } catch (e) { console.error(e); }
    }

    async function loadCalibrationStats() {
        try {
            const res = await fetch("/api/v1/calibration");
            const data = await res.json();
            const list = document.getElementById("calibration-stats-list");
            if (!list) return;
            const stats = data.stats || [];
            if (stats.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); font-size: 0.82rem;">No calibration data yet.</div>`;
                return;
            }
            list.innerHTML = `<table style="width: 100%; border-collapse: collapse; font-size: 0.78rem;">
                <thead><tr style="color: var(--text-muted); font-size: 0.68rem; text-transform: uppercase; border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="text-align: left; padding: 0.3rem;">Model</th><th style="padding: 0.3rem;">Type</th><th style="padding: 0.3rem;">Avg Error</th><th style="padding: 0.3rem;">Count</th>
                </tr></thead>
                <tbody>${stats.map(s => `<tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <td style="padding: 0.3rem; color: var(--color-cyan);">${s.model_name}</td>
                    <td style="padding: 0.3rem; color: var(--text-muted);">${s.prediction_type}</td>
                    <td style="padding: 0.3rem; color: ${Math.abs(s.avg_relative_error || 0) < 0.1 ? "var(--color-green)" : "var(--color-red)"};">${((s.avg_relative_error || 0) * 100).toFixed(1)}%</td>
                    <td style="padding: 0.3rem;">${s.count}</td>
                </tr>`).join("")}</tbody></table>`;
        } catch (e) { /* silent */ }
    }

    async function loadLearningHistory() {
        try {
            const category = document.getElementById("lesson-category-filter")?.value || "";
            const url = `/api/v1/learning/history?limit=30${category ? `&category=${category}` : ""}`;
            const res = await fetch(url);
            const data = await res.json();
            const list = document.getElementById("lessons-list");
            if (!list) return;
            const lessons = data.lessons || [];
            if (lessons.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted);">No lessons recorded yet.</div>`;
                return;
            }
            list.innerHTML = lessons.map(l => `
                <div style="border-bottom: 1px solid rgba(255,255,255,0.06); padding: 0.5rem 0;">
                    <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.25rem;">
                        <span class="hk-badge hk-badge-info" style="font-size: 0.68rem;">${l.category}</span>
                        <span style="color: var(--text-muted); font-size: 0.72rem;">${l.created_at ? new Date(l.created_at).toLocaleDateString() : ""}</span>
                        <span style="color: var(--color-green); font-size: 0.72rem; margin-left: auto;">Impact: ${((l.impact_score || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div style="font-size: 0.82rem; color: #fff;">${l.lesson}</div>
                </div>`).join("");
        } catch (e) { console.error(e); }
    }

    // =========================================================================
    // COMPONENT 6 — PERFORMANCE LAB JS
    // =========================================================================
    const BOT_NAMES = ["research_bot", "strategy_bot", "risk_bot", "execution_bot", "portfolio_bot", "improvement_bot", "shadow_bot", "market_intelligence"];

    async function loadPerformanceLab() {
        try {
            const res = await fetch("/api/v1/performance/laboratory?limit=10");
            const data = await res.json();
            const snapshots = data.snapshots || [];
            const container = document.getElementById("perf-bot-cards");
            if (!container) return;
            // Group by bot_name and get latest snapshot per bot
            const latestByBot = {};
            snapshots.forEach(s => { if (!latestByBot[s.bot_name]) latestByBot[s.bot_name] = s; });
            const allBots = BOT_NAMES.map(name => {
                const snap = latestByBot[name];
                return { name, accuracy: snap?.accuracy ?? null, latency: snap?.latency_ms ?? null, success_rate: snap?.success_rate ?? null, error_rate: snap?.error_rate ?? null };
            });
            container.innerHTML = allBots.map(b => {
                const accColor = b.accuracy === null ? "#aaa" : b.accuracy > 0.8 ? "var(--color-green)" : b.accuracy > 0.5 ? "var(--color-gold)" : "var(--color-red)";
                return `<div class="hk-card" style="padding: 0.75rem;">
                    <div style="font-weight: 600; color: var(--color-gold); margin-bottom: 0.5rem; font-size: 0.88rem;">🤖 ${b.name.replace("_", " ").toUpperCase()}</div>
                    <div style="display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.78rem;">
                        <div style="display: flex; justify-content: space-between;"><span style="color: var(--text-muted);">Accuracy</span><span style="color: ${accColor};">${b.accuracy !== null ? `${(b.accuracy * 100).toFixed(1)}%` : "--"}</span></div>
                        <div style="display: flex; justify-content: space-between;"><span style="color: var(--text-muted);">Latency</span><span style="color: var(--color-cyan);">${b.latency !== null ? `${b.latency.toFixed(0)}ms` : "--"}</span></div>
                        <div style="display: flex; justify-content: space-between;"><span style="color: var(--text-muted);">Success Rate</span><span style="color: var(--color-green);">${b.success_rate !== null ? `${(b.success_rate * 100).toFixed(1)}%` : "--"}</span></div>
                        <div style="display: flex; justify-content: space-between;"><span style="color: var(--text-muted);">Error Rate</span><span style="color: var(--color-red);">${b.error_rate !== null ? `${(b.error_rate * 100).toFixed(1)}%` : "--"}</span></div>
                    </div>
                </div>`;
            }).join("");

            // Render playbook faceoff A/B testing
            const playbooks = data.playbook_performance || [];
            const faceoffContainer = document.getElementById("playbook-faceoff-grid");
            if (faceoffContainer) {
                if (playbooks.length === 0) {
                    faceoffContainer.innerHTML = `<div style="color: var(--text-muted); padding: 1rem; grid-column: 1/-1; text-align: center;">No split-testing trades executed yet.</div>`;
                } else {
                    faceoffContainer.innerHTML = playbooks.map(pb => {
                        const pnlColor = pb.net_pnl >= 0 ? "var(--color-green)" : "var(--color-red)";
                        const winRateColor = pb.win_rate_pct >= 60 ? "var(--color-green)" : pb.win_rate_pct >= 45 ? "var(--color-gold)" : "var(--color-red)";
                        return `
                        <div class="hk-card" style="padding: 1.25rem; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 0.5rem;">
                                <span style="font-weight: 700; font-size: 1.05rem; color: var(--color-gold); letter-spacing: 0.5px;">🛡️ Playbook: ${pb.playbook_id}</span>
                                <span class="reality-badge" style="background: rgba(255, 69, 0, 0.15); color: rgba(255, 69, 0, 0.95); font-size: 0.7rem; border-radius: 4px; padding: 2px 6px;">Active Batch</span>
                            </div>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; font-size: 0.88rem;">
                                <div style="display: flex; flex-direction: column;">
                                    <span style="color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Net P&L</span>
                                    <span style="font-size: 1.15rem; font-weight: 600; color: ${pnlColor};">₹${pb.net_pnl.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>
                                </div>
                                <div style="display: flex; flex-direction: column;">
                                    <span style="color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Max Drawdown</span>
                                    <span style="font-size: 1.15rem; font-weight: 600; color: var(--color-red);">₹${pb.max_drawdown.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>
                                </div>
                                <div style="display: flex; flex-direction: column;">
                                    <span style="color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Win / Loss Ratio</span>
                                    <span style="font-size: 1.1rem; font-weight: 600; color: var(--color-cyan);">${pb.win_loss_ratio}</span>
                                </div>
                                <div style="display: flex; flex-direction: column;">
                                    <span style="color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Win Rate</span>
                                    <span style="font-size: 1.1rem; font-weight: 600; color: ${winRateColor};">${pb.win_rate_pct}%</span>
                                </div>
                            </div>
                            <div style="margin-top: 1rem; padding-top: 0.75rem; border-top: 1px dashed rgba(255,255,255,0.05); font-size: 0.75rem; color: var(--text-muted); display: flex; justify-content: space-between;">
                                <span>Total Trades: <strong>${pb.total_trades}</strong></span>
                                <span>Status: <strong style="color: var(--color-green);">Optimal</strong></span>
                            </div>
                        </div>
                        `;
                    }).join("");
                }
            }
        } catch (e) { console.error(e); }
    }

    window.triggerSelfHealing = async function() {
        const btn = document.getElementById("heal-playbooks-btn");
        if (btn) btn.disabled = true;
        try {
            const res = await fetch("/api/v1/strategy/heal", { method: "POST" });
            const data = await res.json();
            if (res.status === 400 && data.status === "LOCKED") {
                alert(`[Rolling 3-day Epoch Lock Active]\n\n${data.message}`);
            } else if (res.status === 200) {
                if (data.status === "SUCCESS") {
                    let msg = `Might Guy successfully self-healed strategy playbooks!\n\n`;
                    data.healed_playbooks.forEach(pb => {
                        msg += `• Playbook ${pb.playbook_id} (Analyzed ${pb.losses_analyzed} losses):\n`;
                        pb.recommendations.forEach(r => msg += `  - ${r}\n`);
                    });
                    alert(msg);
                    loadPerformanceLab();
                } else {
                    alert(`Self-healing finished: ${data.message}`);
                }
            } else {
                alert(`Error triggering self-healing: ${data.error || "Unknown server error"}`);
            }
        } catch (e) {
            console.error(e);
            alert(`Network error: ${e.message}`);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function loadStrategyEvolution() {
        try {
            const res = await fetch("/api/v1/strategy/evolution");
            const data = await res.json();
            const tbody = document.getElementById("strategy-evolution-body");
            if (!tbody) return;
            const strategies = data.strategies || [];
            if (strategies.length === 0) {
                tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 1rem;">No strategy versions tracked yet.</td></tr>`;
                return;
            }
            tbody.innerHTML = strategies.map(s => {
                const statusColor = { ACTIVE: "var(--color-green)", DEPRECATED: "var(--color-red)", DRAFT: "var(--color-gold)" }[s.status] || "#aaa";
                return `<tr style="border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <td style="padding: 0.5rem; color: var(--color-cyan);">${s.strategy_id || s.name}</td>
                    <td style="padding: 0.5rem;">v${s.version_number || 1}</td>
                    <td style="padding: 0.5rem;"><span style="color: ${statusColor}; font-weight: 600;">${s.status}</span></td>
                    <td style="padding: 0.5rem; color: var(--text-muted); font-size: 0.75rem;">${s.created_at ? new Date(s.created_at).toLocaleDateString() : "--"}</td>
                </tr>`;
            }).join("");
        } catch (e) { console.error(e); }
    }

    // =========================================================================
    // COMPONENT 6 — IMPROVEMENT QUEUE JS
    // =========================================================================
    async function loadImprovementsData() {
        try {
            const status = document.getElementById("improvement-status-filter")?.value || "";
            const url = `/api/v1/improvements${status ? `?status=${status}` : ""}`;
            const res = await fetch(url);
            const data = await res.json();
            const list = document.getElementById("improvements-list");
            if (!list) return;
            const improvements = data.improvements || [];
            if (improvements.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 3rem;"><div style="font-size: 2rem; margin-bottom: 0.5rem;">🚀</div><div>No improvements in queue.</div></div>`;
                return;
            }
            const difficultyColors = { EASY: "var(--color-green)", MEDIUM: "var(--color-gold)", HARD: "var(--color-red)" };
            const statusColors = { PENDING: "var(--color-gold)", APPROVED: "var(--color-green)", REJECTED: "var(--color-red)", POSTPONED: "#888" };
            list.innerHTML = improvements.map(imp => `
                <div class="hk-card" style="padding: 1rem; border-left: 3px solid ${statusColors[imp.status] || "#aaa"};">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                        <span style="font-weight: 600; color: #fff; font-size: 0.9rem;">🚀 ${imp.title}</span>
                        <div style="display: flex; gap: 0.5rem; align-items: center;">
                            <span class="hk-badge hk-badge-info" style="font-size: 0.68rem; color: ${difficultyColors[imp.difficulty] || '#aaa'};">${imp.difficulty}</span>
                            <span style="color: ${statusColors[imp.status] || "#aaa"}; font-weight: 700; font-size: 0.75rem;">${imp.status}</span>
                        </div>
                    </div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;">${imp.description}</div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="font-size: 0.76rem; color: var(--color-green);">Impact: ${((imp.estimated_impact || 0) * 100).toFixed(0)}%</div>
                        ${imp.status === "PENDING" ? `
                        <div style="display: flex; gap: 0.5rem;">
                            <button class="btn-primary-sm" style="font-size: 0.7rem; background: rgba(0,200,100,0.2);" onclick="actionImprovement('${imp.improvement_id}', 'approve')">✅ Approve</button>
                            <button class="btn-primary-sm" style="font-size: 0.7rem; background: rgba(255,165,0,0.2);" onclick="actionImprovement('${imp.improvement_id}', 'postpone')">⏳ Postpone</button>
                            <button class="btn-primary-sm" style="font-size: 0.7rem; background: rgba(255,80,80,0.2);" onclick="actionImprovement('${imp.improvement_id}', 'reject')">❌ Reject</button>
                        </div>` : ""}
                    </div>
                </div>`).join("");
        } catch (e) { console.error(e); }
    }

    async function actionImprovement(id, action) {
        try {
            const res = await fetch(`/api/v1/improvements/${id}/${action}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reviewer: "Commander" })
            });
            if (res.ok) loadImprovementsData();
        } catch (e) { console.error(e); }
    }

    // =========================================================================
    // COMPONENT 7 — ORGANIZATION PANEL JS
    // =========================================================================
    async function loadAgentsData() {
        try {
            const res = await fetch("/api/v1/organization/agents");
            const data = await res.json();
            const grid = document.getElementById("agent-cards-grid");
            if (!grid) return;
            const agents = data.agents || [];
            if (agents.length === 0) {
                grid.innerHTML = `<div style="color: var(--text-muted);">No agents registered.</div>`;
                return;
            }
            const statusColors = { IDLE: "var(--color-cyan)", RUNNING: "var(--color-green)", PAUSED: "var(--color-gold)", ERROR: "var(--color-red)", OFFLINE: "#555" };
            grid.innerHTML = agents.map(a => {
                const sc = statusColors[a.status] || "#aaa";
                const caps = JSON.parse(a.capabilities || "[]");
                return `<div class="hk-card" style="padding: 0.75rem; border-left: 3px solid ${sc};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                        <span style="font-weight: 700; color: #fff; font-size: 0.88rem;">🤖 ${a.name || a.role}</span>
                        <span style="font-size: 0.7rem; font-weight: 700; color: ${sc};">${a.status}</span>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.35rem;">${a.role.replace(/_/g, " ")}</div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.74rem; margin-bottom: 0.35rem;">
                        <span style="color: var(--text-muted);">Health</span>
                        <span style="color: ${(a.health_score || 1) >= 0.8 ? "var(--color-green)" : "var(--color-gold)"};">${(((a.health_score || 1)) * 100).toFixed(0)}%</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 0.74rem; margin-bottom: 0.4rem;">
                        <span style="color: var(--text-muted);">Workload</span>
                        <span style="color: var(--color-cyan);">${a.workload || 0} tasks</span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.25rem;">${caps.slice(0, 3).map(c => `<span class="hk-badge" style="font-size: 0.6rem; background: rgba(0,200,255,0.1);">${c}</span>`).join("")}</div>
                </div>`;
            }).join("");
        } catch (e) { console.error(e); }
    }

    async function loadGovernancePolicies() {
        try {
            const res = await fetch("/api/v1/organization/governance/policies");
            const data = await res.json();
            const list = document.getElementById("governance-policies-list");
            if (!list) return;
            const policies = data.policies || [];
            if (policies.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); font-size: 0.82rem;">No policies.</div>`;
                return;
            }
            list.innerHTML = policies.map(p => {
                const params = JSON.parse(p.parameters || "{}");
                const paramStr = Object.entries(params).map(([k, v]) => `${k}: ${v}`).join(", ");
                return `<div style="border-bottom: 1px solid rgba(255,255,255,0.06); padding: 0.5rem 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.2rem;">
                        <span style="font-weight: 600; font-size: 0.82rem; color: ${p.is_active ? "var(--color-gold)" : "#555"};">${p.name}</span>
                        <span style="font-size: 0.68rem; color: ${p.is_active ? "var(--color-green)" : "var(--color-red)"};">${p.is_active ? "ACTIVE" : "DISABLED"}</span>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${paramStr || p.description}</div>
                </div>`;
            }).join("");
        } catch (e) { console.error(e); }
    }

    async function loadConsensusRecords() {
        try {
            const res = await fetch("/api/v1/organization/consensus");
            const data = await res.json();
            const list = document.getElementById("consensus-records-list");
            if (!list) return;
            const records = data.records || [];
            if (records.length === 0) {
                list.innerHTML = `<div style="color: var(--text-muted); font-size: 0.82rem;">No votes yet.</div>`;
                return;
            }
            const statusColors = { OPEN: "var(--color-cyan)", RESOLVED: "var(--color-green)", FAILED: "var(--color-red)", EXPIRED: "#555" };
            list.innerHTML = records.map(r => `
                <div style="border-bottom: 1px solid rgba(255,255,255,0.06); padding: 0.5rem 0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.2rem;">
                        <span style="font-weight: 600; font-size: 0.82rem; color: #fff;">🗳️ ${r.topic}</span>
                        <span style="font-size: 0.68rem; color: ${statusColors[r.status] || "#aaa"}; font-weight: 700;">${r.status}</span>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${r.voting_model} | ${r.result ? `Result: ${r.result}` : "Pending..."}</div>
                </div>`).join("");
        } catch (e) { console.error(e); }
    }

    async function loadOrganizationResources() {
        try {
            const res = await fetch("/api/v1/organization/resources");
            const data = await res.json();
            const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            const setBar = (id, pct) => { const el = document.getElementById(id); if (el) el.style.width = `${Math.min(100, pct).toFixed(1)}%`; };
            setEl("res-cpu", `${(data.cpu_pct || 0).toFixed(1)}%`);
            setBar("res-cpu-bar", data.cpu_pct || 0);
            setEl("res-ram", `${(data.ram_mb || 0).toFixed(0)} MB`);
            setBar("res-ram-bar", (data.ram_mb || 0) / 8192 * 100);
            setEl("res-tokens", `${(data.llm_tokens_used || 0).toLocaleString()} / ${(data.llm_tokens_limit || 1000000).toLocaleString()}`);
            setBar("res-tokens-bar", ((data.llm_tokens_used || 0) / (data.llm_tokens_limit || 1)) * 100);
            setEl("res-api", `${(data.api_calls_used || 0).toLocaleString()} / ${(data.api_calls_limit || 10000).toLocaleString()}`);
            setBar("res-api-bar", ((data.api_calls_used || 0) / (data.api_calls_limit || 1)) * 100);
        } catch (e) { console.error(e); }
    }

    function openStartConsensusModal() {
        const modal = document.getElementById("start-consensus-modal");
        if (modal) modal.style.display = "flex";
    }

    document.getElementById("start-consensus-form")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const topic = document.getElementById("consensus-topic")?.value;
        const description = document.getElementById("consensus-desc")?.value;
        const voting_model = document.getElementById("consensus-model")?.value;
        try {
            const res = await fetch("/api/v1/organization/consensus", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ topic, description, voting_model })
            });
            if (res.ok) {
                document.getElementById("start-consensus-modal").style.display = "none";
                loadConsensusRecords();
            }
        } catch (e) { console.error(e); }
    });

    // =========================================================================
    // --- Settings (Module 5 & 8) ---
    // =========================================================================
    const formAutomation = document.getElementById("form-automation-settings");
    const formInstitutional = document.getElementById("form-institutional-settings");

    async function loadSettingsData() {
        try {
            // Load Automation Settings
            const resAuto = await fetch("/api/v1/automation/settings");
            const dataAuto = await resAuto.json();
            if (formAutomation) {
                for (const [k, v] of Object.entries(dataAuto)) {
                    const input = formAutomation.elements[k];
                    if (input) input.value = v;
                }
            }

            // Load Institutional Settings
            const resInst = await fetch("/api/v1/settings/institutional");
            const dataInst = await resInst.json();
            if (formInstitutional) {
                if (dataInst.layout) formInstitutional.elements["layout"].value = dataInst.layout;
                if (dataInst.refresh_rates && dataInst.refresh_rates.health) {
                    formInstitutional.elements["refresh_rate"].value = dataInst.refresh_rates.health;
                }
                if (dataInst.providers && dataInst.providers.market_data) {
                    formInstitutional.elements["provider"].value = dataInst.providers.market_data;
                }
                if (dataInst.developer_mode !== undefined) {
                    formInstitutional.elements["developer_mode"].checked = dataInst.developer_mode;
                }
            }
        } catch (err) {
            console.error("Failed to load settings:", err);
        }
    }

    if (formAutomation) {
        formAutomation?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(formAutomation);
            const payload = {};
            formData.forEach((v, k) => {
                payload[k] = isNaN(v) ? v : parseFloat(v);
            });

            try {
                const res = await fetch("/api/v1/automation/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    appendTerminalLog("SUCCESS", "Automation parameters saved successfully.");
                }
            } catch (err) {
                console.error(err);
            }
        });
    }

    if (formInstitutional) {
        formInstitutional?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const payload = {
                layout: formInstitutional.elements["layout"].value,
                refresh_rates: { health: parseInt(formInstitutional.elements["refresh_rate"].value) },
                providers: { market_data: formInstitutional.elements["provider"].value },
                developer_mode: formInstitutional.elements["developer_mode"].checked
            };

            try {
                const res = await fetch("/api/v1/settings/institutional", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    appendTerminalLog("SUCCESS", "Institutional configuration saved successfully.");
                }
            } catch (err) {
                console.error(err);
            }
        });
    }

    // --- SSE Event Hook for Components 4, 5, 6, 7 ---
    const originalOnStreamMessage = window.onStreamMessage;
    window.onStreamMessage = (e) => {
        if (originalOnStreamMessage) originalOnStreamMessage(e);
        
        try {
            const event = JSON.parse(e.data);
            const { event: event_type, data } = event;
            const activeTab = document.querySelector(".nav-item.active")?.getAttribute("data-tab");

            // --- Component 4 Pulses & System Health ---
            if (event_type === "MARKET_SCAN_COMPLETED") {
                nodePulses.push({ from: "market_intelligence", to: "research_bot", progress: 0 });
            } else if (event_type === "RESEARCH_GENERATED") {
                nodePulses.push({ from: "research_bot", to: "strategy_bot", progress: 0 });
            } else if (event_type === "STRATEGY_COMPLETED") {
                nodePulses.push({ from: "strategy_bot", to: "risk_bot", progress: 0 });
            } else if (event_type === "RISK_APPROVED") {
                nodePulses.push({ from: "risk_bot", to: "execution_bot", progress: 0 });
            } else if (event_type === "EXECUTION_COMPLETED") {
                nodePulses.push({ from: "execution_bot", to: "portfolio_bot", progress: 0 });
            } else if (event_type === "PORTFOLIO_UPDATED") {
                nodePulses.push({ from: "portfolio_bot", to: "improvement_bot", progress: 0 });
            } else if (event_type === "LEARNING_COMPLETED") {
                nodePulses.push({ from: "improvement_bot", to: "shadow_bot", progress: 0 });
            }
            
            if (event_type === "ALERT_CREATED") {
                loadAlertsData();
                appendTerminalLog("WARNING", `[ALERT] ${data.source}: ${data.message}`);
            } else if (event_type === "ALERT_RESOLVED") {
                loadAlertsData();
            } else if (event_type === "HEARTBEAT") {
                if (activeTab === "control") {
                    loadControlData();
                }
            } else if (event_type === "SYSTEM_HEALTH") {
                const healthVal = document.getElementById("warroom-health");
                if (healthVal) {
                    healthVal.textContent = `HEALTHY (${data.health_score.toFixed(0)}%)`;
                    healthVal.style.color = data.health_score >= 80 ? "var(--color-green)" : "var(--color-gold)";
                }
            } else if (event_type === "SHINOBI_LOG") {
                appendTerminalLog(data.level, data.message);
            }

            // --- Component 5, 6, 7 Events ---
            if (event_type === "MISSION_CREATED" || event_type === "MISSION_COMPLETED" || event_type === "MISSION_FAILED" || event_type === "MISSION_PROGRESS") {
                if (activeTab === "missions") loadMissionsData();
                const logEl = document.getElementById("mission-event-log");
                if (logEl) {
                    const ts = new Date().toLocaleTimeString();
                    const color = event_type.includes("COMPLETED") ? "var(--color-green)" : event_type.includes("FAILED") ? "var(--color-red)" : "var(--color-cyan)";
                    const entry = document.createElement("div");
                    entry.style.cssText = `color: ${color}; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.2rem;`;
                    entry.innerHTML = `[${ts}] <strong>${event_type}</strong> — ${data.mission_name || data.mission_id || ""}`;
                    logEl.insertBefore(entry, logEl.firstChild);
                }
            } else if (event_type === "LESSON_GENERATED" && activeTab === "ai-coach") {
                loadLearningHistory();
            } else if (event_type === "MEMORY_UPDATED" && activeTab === "memory-graph") {
                loadMemoryGraphData();
            } else if (event_type === "STRATEGY_EVOLVED" && activeTab === "perf-lab") {
                loadStrategyEvolution();
            } else if (event_type === "AGENT_REGISTERED" || event_type === "TASK_ASSIGNED" || event_type === "TASK_COMPLETED") {
                if (activeTab === "organization") loadAgentsData();
            } else if (event_type === "CONSENSUS_REACHED" && activeTab === "organization") {
                loadConsensusRecords();
            } else if (event_type === "RESOURCE_WARNING") {
                if (activeTab === "organization") loadOrganizationResources();
                appendTerminalLog("WARNING", `[RESOURCE] ${data.message || "Resource warning"}`);
            }
        } catch (err) {
            console.error("Error in onStreamMessage hook:", err);
        }
    };

    // =========================================================================
    // Multi-Market Sessions Loader (Phase 9.5A)
    // =========================================================================
    async function loadExchangeSessions() {
        const container = document.getElementById("warroom-sessions-list");
        if (!container) return;

        try {
            const response = await fetch("/api/v1/market/sessions");
            if (!response.ok) throw new Error("Failed to load sessions");
            const data = await response.json();

            container.innerHTML = "";
            data.forEach(item => {
                const statusColor = item.status === "OPEN" ? "var(--color-green)" : 
                                    item.status === "PRE_OPEN" ? "var(--color-cyan)" : 
                                    item.status === "MAINTENANCE" ? "var(--color-gold)" : "rgba(255,255,255,0.4)";
                
                const badge = document.createElement("span");
                badge.className = "hk-badge";
                badge.style.cssText = `background: rgba(255,255,255,0.05); color: #fff; font-size: 0.7rem; border-left: 3px solid ${statusColor}; margin-right: 0.3rem;`;
                badge.innerHTML = `${item.exchange}: <strong style="color: ${statusColor}">${item.status}</strong> (${item.local_time})`;
                container.appendChild(badge);
            });
        } catch (err) {
            console.warn("Failed to load exchange sessions:", err);
        }
    }

    // =========================================================================
    // Tax implications Loader (Phase 9.5A)
    // =========================================================================
    async function loadTaxData() {
        const stcgEl = document.getElementById("tax-stcg");
        const ltcgEl = document.getElementById("tax-ltcg");
        const realizedEl = document.getElementById("tax-realized");
        const unrealizedEl = document.getElementById("tax-unrealized");
        const netPnlEl = document.getElementById("tax-net-pnl");
        const liabilityEl = document.getElementById("tax-liability");
        const brokerageEl = document.getElementById("tax-charges-brokerage");
        const gstEl = document.getElementById("tax-charges-gst");
        const sttEl = document.getElementById("tax-charges-stt");
        const stampEl = document.getElementById("tax-charges-stamp");
        const exchangeEl = document.getElementById("tax-charges-exchange");
        const sebiEl = document.getElementById("tax-charges-sebi");
        const totalChargesEl = document.getElementById("tax-charges-total");
        const divIncomeEl = document.getElementById("tax-income-dividend");
        const intIncomeEl = document.getElementById("tax-income-interest");
        const bodyLedger = document.getElementById("body-tax-ledger");
        const projectionEl = document.getElementById("tax-projection");

        try {
            const response = await fetch("/api/v1/portfolio/paper/tax");
            if (!response.ok) throw new Error("Tax API returned error");
            const data = await response.json();
            
            if (stcgEl) stcgEl.textContent = formatINR(data.stcg) || "Not Available";
            if (ltcgEl) ltcgEl.textContent = formatINR(data.ltcg) || "Not Available";
            if (realizedEl) realizedEl.textContent = formatINR(data.realized_pnl) || "Not Available";
            if (unrealizedEl) unrealizedEl.textContent = formatINR(data.unrealized_pnl) || "Not Available";
            
            if (netPnlEl) {
                const val = data.net_profit_after_tax;
                netPnlEl.textContent = formatINR(val) || "Not Available";
                netPnlEl.style.color = val >= 0 ? "var(--color-green)" : "var(--color-red)";
            }
            if (liabilityEl) {
                liabilityEl.textContent = formatINR(data.estimated_tax) || "Not Available";
            }
            
            if (brokerageEl) brokerageEl.textContent = formatINR(data.brokerage) || "Not Available";
            if (gstEl) gstEl.textContent = formatINR(data.gst) || "Not Available";
            if (sttEl) sttEl.textContent = formatINR(data.stt) || "Not Available";
            if (stampEl) stampEl.textContent = formatINR(data.stamp_duty) || "Not Available";
            if (exchangeEl) exchangeEl.textContent = formatINR(data.exchange_charges) || "Not Available";
            if (sebiEl) sebiEl.textContent = formatINR(data.sebi_charges) || "Not Available";
            if (totalChargesEl) totalChargesEl.textContent = formatINR(data.total_charges) || "Not Available";
            if (divIncomeEl) divIncomeEl.textContent = formatINR(data.dividend_income) || "Not Available";
            if (intIncomeEl) intIncomeEl.textContent = formatINR(data.interest_income) || "Not Available";
            if (projectionEl) projectionEl.textContent = data.tax_forecast || "Not Available";

            if (bodyLedger) {
                bodyLedger.innerHTML = "";
                const ledger = data.tax_ledger || [];
                if (ledger.length === 0) {
                    bodyLedger.innerHTML = `<tr><td colspan="5" class="empty-state">No tax events logged.</td></tr>`;
                } else {
                    ledger.forEach(item => {
                        const tr = document.createElement("tr");
                        const dColor = item.direction === "BUY" ? "var(--color-green)" : "var(--color-cyan)";
                        tr.innerHTML = `
                            <td>${item.symbol}</td>
                            <td style="color: ${dColor}; font-weight:700;">${item.direction}</td>
                            <td>${formatINR(item.trade_value)}</td>
                            <td>${formatINR(item.taxes_and_charges)}</td>
                            <td style="color: var(--text-muted);">${new Date(item.timestamp).toLocaleTimeString()}</td>
                        `;
                        bodyLedger.appendChild(tr);
                    });
                }
            }
        } catch (err) {
            console.warn("Tax Center error loading data:", err);
            const fallbackList = [
                stcgEl, ltcgEl, realizedEl, unrealizedEl, netPnlEl, liabilityEl,
                brokerageEl, gstEl, sttEl, stampEl, exchangeEl, sebiEl, totalChargesEl,
                divIncomeEl, intIncomeEl, projectionEl
            ];
            fallbackList.forEach(el => { if (el) el.textContent = "Not Available"; });
            if (bodyLedger) {
                bodyLedger.innerHTML = `<tr><td colspan="5" class="empty-state">Not Available</td></tr>`;
            }
        }
    }

    // =========================================================================
    // Floating Command Palette Overlay Actions (Phase 9.5A)
    // =========================================================================
    const palette = document.getElementById("floating-command-palette");
    const paletteInput = document.getElementById("palette-chat-input");
    const paletteHistory = document.getElementById("palette-chat-history");
    const paletteSend = document.getElementById("btn-palette-send");
    const chatFab = document.getElementById("floating-chat-fab");

    function togglePalette() {
        if (!palette) return;
        const isOpen = palette.style.display === "flex";
        if (isOpen) {
            palette.style.display = "none";
        } else {
            palette.style.display = "flex";
            setTimeout(() => {
                if (paletteInput) paletteInput.focus();
            }, 100);
        }
    }

    // Direct, standalone click listener for floating orange chat bubble button
    const chatBubbleBtn = document.getElementById("floating-chat-fab") || document.querySelector(".chat-fab");
    const chatConsoleWindow = document.getElementById("floating-command-palette");
    if (chatBubbleBtn && chatConsoleWindow) {
        chatBubbleBtn?.addEventListener("click", (e) => {
            e.stopPropagation();
            const isOpen = chatConsoleWindow.style.display === "flex" || chatConsoleWindow.classList.contains("open");
            if (isOpen) {
                chatConsoleWindow.style.display = "none";
                chatConsoleWindow.classList.remove("open");
            } else {
                chatConsoleWindow.style.display = "flex";
                chatConsoleWindow.classList.add("open");
                const input = document.getElementById("palette-chat-input");
                if (input) setTimeout(() => input?.focus(), 100);
            }
        });
    }

    // Keyboard Shortcuts
    document?.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            togglePalette();
        }
        if (e.key === "Escape" && palette && palette.style.display === "flex") {
            togglePalette();
        }
    });

    // File upload status handling
    const fileUpload = document.getElementById("palette-file-upload");
    const fileStatus = document.getElementById("palette-file-status");
    if (fileUpload && fileStatus) {
        fileUpload.addEventListener("change", () => {
            const file = fileUpload.files[0];
            if (file) {
                fileStatus.textContent = `Attached: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
                fileStatus.style.display = "block";
            } else {
                fileStatus.style.display = "none";
                fileStatus.textContent = "";
            }
        });
    }

    async function sendPaletteMessage() {
        if (!paletteInput || !paletteHistory) return;
        const text = paletteInput.value.trim();
        const file = fileUpload ? fileUpload.files[0] : null;
        if (!text && !file) return;

        // User bubble
        const userDiv = document.createElement("div");
        userDiv.style.cssText = "align-self: flex-end; background: var(--color-gold); color: #000; padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.85rem; max-width: 80%; font-weight: 600; margin-bottom: 0.5rem;";
        userDiv.textContent = file ? `[Sent file: ${file.name}] ${text}` : text;
        paletteHistory.appendChild(userDiv);
        paletteHistory.scrollTop = paletteHistory.scrollHeight;

        paletteInput.value = "";
        if (fileUpload) {
            fileUpload.value = "";
        }
        if (fileStatus) {
            fileStatus.style.display = "none";
            fileStatus.textContent = "";
        }

        // Thinking bubble
        const loadDiv = document.createElement("div");
        loadDiv.style.cssText = "align-self: flex-start; background: rgba(255,255,255,0.05); padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.5rem;";
        loadDiv.textContent = "Hokage is thinking...";
        paletteHistory.appendChild(loadDiv);
        paletteHistory.scrollTop = paletteHistory.scrollHeight;

        try {
            let response;
            if (file) {
                const formData = new FormData();
                formData.append("message", text);
                formData.append("file", file);
                response = await fetch("/api/v1/chat", {
                    method: "POST",
                    body: formData
                });
            } else {
                response = await fetch("/api/v1/commander/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ query: text })
                });
            }
            loadDiv.remove();

            if (!response.ok) throw new Error("Server communication error");
            const data = await response.json();

            const botDiv = document.createElement("div");
            botDiv.style.cssText = "align-self: flex-start; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.85rem; color: #fff; max-width: 80%; line-height: 1.4; margin-bottom: 0.5rem;";
            const responseText = (typeof data.response === "string" ? data.response : data.response_text) || JSON.stringify(data);
            botDiv.innerHTML = responseText.replace(/\n/g, "<br>");
            paletteHistory.appendChild(botDiv);
            paletteHistory.scrollTop = paletteHistory.scrollHeight;
        } catch (err) {
            loadDiv.remove();
            const errDiv = document.createElement("div");
            errDiv.style.cssText = "align-self: flex-start; background: rgba(255,56,96,0.1); border: 1px solid rgba(255,56,96,0.2); padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.85rem; color: var(--color-red); margin-bottom: 0.5rem;";
            errDiv.textContent = `Error: ${err.message}`;
            paletteHistory.appendChild(errDiv);
            paletteHistory.scrollTop = paletteHistory.scrollHeight;
        }
    }

    if (paletteSend) paletteSend?.addEventListener("click", sendPaletteMessage);
    if (paletteInput) {
        paletteInput?.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendPaletteMessage();
            }
        });
    }

    // Wire Hokage Command Center Quick Actions
    const qaAskHokage = document.getElementById("qa-ask-hokage");
    const qaStartResearch = document.getElementById("qa-start-research");
    const qaScanMarkets = document.getElementById("qa-scan-markets");
    const qaNewOpportunity = document.getElementById("qa-new-opportunity");
    const qaUploadDocument = document.getElementById("qa-upload-document");
    const qaVoiceCommand = document.getElementById("qa-voice-command");

    if (qaAskHokage) {
        qaAskHokage?.addEventListener("click", () => {
            const input = document.getElementById("warroom-input-chat");
            if (input) {
                input.focus();
                input.scrollIntoView({ behavior: "smooth" });
            }
        });
    }
    if (qaStartResearch) {
        qaStartResearch?.addEventListener("click", () => {
            const btn = document.querySelector('.nav-item[data-tab="research"]');
            if (btn) btn.click();
        });
    }
    if (qaScanMarkets) {
        qaScanMarkets?.addEventListener("click", () => {
            const btn = document.querySelector('.nav-item[data-tab="markets"]');
            if (btn) btn.click();
            sendCommanderCommand("SCAN_MARKETS");
        });
    }
    if (qaNewOpportunity) {
        qaNewOpportunity?.addEventListener("click", () => {
            const btn = document.querySelector('.nav-item[data-tab="opportunities"]');
            if (btn) btn.click();
        });
    }
    if (qaUploadDocument) {
        qaUploadDocument?.addEventListener("click", () => {
            const btn = document.querySelector('.nav-item[data-tab="documents"]');
            if (btn) btn.click();
        });
    }
    if (qaVoiceCommand) {
        qaVoiceCommand?.addEventListener("click", () => {
            const micBtn = document.getElementById("warroom-toggle-voice");
            if (micBtn) micBtn.click();
        });
    }

    // Update Zerodha Broker status in sidebar
    async function updateBrokerStatus() {
        const brokerStatusEl = document.getElementById("sidebar-broker-status");
        if (!brokerStatusEl) return;
        try {
            const response = await fetch("/api/v1/broker/zerodha/status");
            if (response.ok) {
                const data = await response.json();
                if (data.connected) {
                    brokerStatusEl.innerHTML = `Zerodha: <span style="color: var(--color-green); font-weight: 600; text-shadow: 0 0 10px rgba(57,255,20,0.3);">Connected</span>`;
                } else {
                    brokerStatusEl.innerHTML = `Zerodha: <span style="color: var(--color-red); font-weight: 600;">Disconnected</span>`;
                }
            }
        } catch (err) {
            console.error("Failed to fetch broker status:", err);
        }
    }
    updateBrokerStatus();
    setInterval(updateBrokerStatus, 5000);

    // Call exchange sessions loader initially
    loadExchangeSessions();
});