import os

filepath = r"c:\Users\anant\OneDrive\Documents\AI PROJECT\AI COMMAND CENTRE\Hokage\src\hokage\dashboard\templates\index.html"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

start_marker = "<!-- TAB: HOME / WAR ROOM -->"
end_marker = "<!-- TAB: POSITIONS -->"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print("ERROR: Markers not found!")
    exit(1)

new_home_html = """<!-- TAB: HOME / WAR ROOM -->
            <section class="tab-pane active" id="tab-home">
                <!-- WARROOM_STATUS Widget -->
                <div id="WARROOM_STATUS" class="hk-card" style="margin-bottom: 1.5rem; padding: 1rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span class="status-dot-blink" id="warroom-heartbeat"></span>
                            <span style="font-weight: 700; color: var(--text-primary);">HOKAGE CORE STATUS:</span>
                            <span id="warroom-state-display" class="hk-badge hk-badge-info">IDLE</span>
                        </div>
                        <div style="display: flex; gap: 1.5rem; font-size: 0.85rem; color: var(--text-muted);">
                            <div>Market: <strong id="warroom-market-status" style="color: #fff;">CLOSED</strong></div>
                            <div>Session: <strong id="warroom-session" style="color: #fff;">N/A</strong></div>
                            <div>System Health: <strong id="warroom-health" style="color: var(--color-green);">HEALTHY</strong></div>
                            <div>Time: <strong id="warroom-time" style="color: #fff;">--:--:--</strong></div>
                        </div>
                    </div>
                </div>

                <!-- PORTFOLIO_SUMMARY & EQUITY_CURVE & PERSONALITY_CONTROL Row -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem;">
                    <!-- PORTFOLIO_SUMMARY Widget -->
                    <div id="PORTFOLIO_SUMMARY" class="hk-card">
                        <div class="panel-header" style="margin-bottom: 1rem;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Portfolio Summary</h3>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                            <div class="hk-metric-card">
                                <span class="hk-metric-title">Equity</span>
                                <span class="hk-metric-value" id="summary-equity">₹0.00</span>
                            </div>
                            <div class="hk-metric-card">
                                <span class="hk-metric-title">Cash Available</span>
                                <span class="hk-metric-value" id="summary-cash">₹0.00</span>
                            </div>
                            <div class="hk-metric-card">
                                <span class="hk-metric-title">Trust Score</span>
                                <span class="hk-metric-value" id="summary-trust" style="color: var(--color-cyan);">95/100</span>
                            </div>
                            <div class="hk-metric-card">
                                <span class="hk-metric-title">Max Drawdown</span>
                                <span class="hk-metric-value" id="summary-drawdown" style="color: var(--color-red);">0.00%</span>
                            </div>
                        </div>
                    </div>

                    <!-- EQUITY_CURVE Widget -->
                    <div id="EQUITY_CURVE" class="hk-card" style="display: flex; flex-direction: column;">
                        <div class="panel-header" style="margin-bottom: 1rem;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Equity & Performance Curve</h3>
                        </div>
                        <div style="flex: 1; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid var(--border-color); min-height: 150px; position: relative;">
                            <canvas id="equity-curve-canvas" style="width: 100%; height: 100%; max-height: 150px;"></canvas>
                            <div id="equity-curve-empty" style="position: absolute; color: var(--text-muted); font-size: 0.85rem;">Generating real-time curve...</div>
                        </div>
                    </div>

                    <!-- PERSONALITY_CONTROL & VOICE_STATUS Widget -->
                    <div id="PERSONALITY_CONTROL" class="hk-card" style="display: flex; flex-direction: column; justify-content: space-between;">
                        <div>
                            <div class="panel-header" style="margin-bottom: 1rem;">
                                <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Tactical Controls</h3>
                            </div>
                            <div style="margin-bottom: 1rem;">
                                <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 0.5rem;">Hokage Personality</label>
                                <select id="personality-selector" style="width: 100%; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); color: #fff; padding: 0.5rem; border-radius: 6px; font-family: inherit;">
                                    <option value="naruto">Naruto (Seventh Hokage - Confident & Bold)</option>
                                    <option value="hashirama">Hashirama (First Hokage - Balanced & Resilient)</option>
                                    <option value="madara">Madara (Tactical & Aggressive)</option>
                                    <option value="kakashi">Kakashi (Sixth Hokage - Calculated & Conservative)</option>
                                </select>
                            </div>
                        </div>
                        <!-- VOICE_STATUS Widget -->
                        <div id="VOICE_STATUS" style="border-top: 1px solid var(--border-color); padding-top: 1rem; display: flex; align-items: center; justify-content: space-between;">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span class="status-dot-blink" id="voice-active-dot" style="background-color: var(--text-muted); box-shadow: none;"></span>
                                <span style="font-size: 0.85rem; font-weight: 600;" id="voice-active-text">Voice: Inactive</span>
                            </div>
                            <button id="warroom-toggle-voice" class="btn-primary-sm" style="padding: 0.3rem 0.75rem; font-size: 0.75rem;">Toggle Mic</button>
                        </div>
                    </div>
                </div>

                <!-- Main War Room Body (Timeline, Committees, Logs) -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem;">
                    
                    <!-- TIMELINE Widget (Hokage's Thinking) -->
                    <div id="TIMELINE" class="hk-card" style="grid-column: span 2;">
                        <div class="panel-header" style="margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; font-size: 1.1rem; color: var(--color-gold);">Hokage Real-Time Thinking Stream</h3>
                            <span id="timeline-activity-indicator" style="font-size: 0.8rem; color: var(--text-muted);">Status: CALM</span>
                        </div>
                        <div class="timeline-steps-container" style="display: flex; justify-content: space-between; position: relative; padding: 1rem 0; overflow-x: auto;">
                            <!-- Progress Line -->
                            <div style="position: absolute; top: 2.2rem; left: 5%; right: 5%; height: 2px; background: rgba(255,255,255,0.1); z-index: 1;"></div>
                            <div id="timeline-progress-fill" style="position: absolute; top: 2.2rem; left: 5%; width: 0%; height: 2px; background: var(--color-cyan); transition: width 0.5s ease; z-index: 2;"></div>

                            <!-- Timeline Steps -->
                            <div class="timeline-step" data-step="MARKET_SCAN" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">1</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Market Scan</span>
                            </div>
                            <div class="timeline-step" data-step="MACRO_REGIME" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">2</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Macro Regime</span>
                            </div>
                            <div class="timeline-step" data-step="UNIVERSE_SCAN" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">3</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Universe Scan</span>
                            </div>
                            <div class="timeline-step" data-step="STRATEGY_COMMITTEE" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">4</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Strategy Comm</span>
                            </div>
                            <div class="timeline-step" data-step="INVESTMENT_COMMITTEE" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">5</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Investment Comm</span>
                            </div>
                            <div class="timeline-step" data-step="RISK_COMMITTEE" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">6</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Risk Comm</span>
                            </div>
                            <div class="timeline-step" data-step="EXECUTION" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">7</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Execution</span>
                            </div>
                            <div class="timeline-step" data-step="PORTFOLIO_UPDATE" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">8</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Portfolio Update</span>
                            </div>
                            <div class="timeline-step" data-step="SHADOW_ANALYTICS" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">9</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Shadow Analytics</span>
                            </div>
                            <div class="timeline-step" data-step="LEARNING" style="display: flex; flex-direction: column; align-items: center; z-index: 3; position: relative; min-width: 80px;">
                                <div class="step-dot" style="width: 24px; height: 24px; border-radius: 50%; background: #2d3748; border: 2px solid #4a5568; display: flex; align-items: center; justify-content: center; color: #718096; font-size: 0.7rem; font-weight: bold; transition: all 0.3s;">10</div>
                                <span class="step-label" style="font-size: 0.75rem; margin-top: 0.5rem; color: var(--text-muted); font-weight: 500;">Learning</span>
                            </div>
                        </div>
                    </div>

                    <!-- COMMITTEE_PANEL Widget -->
                    <div id="COMMITTEE_PANEL" class="hk-card">
                        <div class="panel-header" style="margin-bottom: 1rem;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Committee Chambers</h3>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 1rem; max-height: 400px; overflow-y: auto;">
                            <!-- Strategy Committee Card -->
                            <div class="hk-committee-card waiting" id="committee-strategy">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong>Strategy Committee</strong>
                                    <span class="hk-badge hk-badge-warning" id="committee-strategy-status">WAITING</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.4rem;">
                                    Vote: <span id="committee-strategy-vote" style="color: #fff;">-</span> |
                                    Confidence: <span id="committee-strategy-confidence" style="color: var(--color-cyan);">-</span> |
                                    Time: <span id="committee-strategy-time">-</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.4rem 0 0 0;" id="committee-strategy-reason">Awaiting next market scan.</p>
                            </div>

                            <!-- Investment Committee Card -->
                            <div class="hk-committee-card waiting" id="committee-investment">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong>Investment Committee</strong>
                                    <span class="hk-badge hk-badge-warning" id="committee-investment-status">WAITING</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.4rem;">
                                    Vote: <span id="committee-investment-vote" style="color: #fff;">-</span> |
                                    Confidence: <span id="committee-investment-confidence" style="color: var(--color-cyan);">-</span> |
                                    Time: <span id="committee-investment-time">-</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.4rem 0 0 0;" id="committee-investment-reason">Awaiting opportunity evaluation.</p>
                            </div>

                            <!-- Risk Committee Card -->
                            <div class="hk-committee-card waiting" id="committee-risk">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong>Risk Committee</strong>
                                    <span class="hk-badge hk-badge-warning" id="committee-risk-status">WAITING</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.4rem;">
                                    Vote: <span id="committee-risk-vote" style="color: #fff;">-</span> |
                                    Confidence: <span id="committee-risk-confidence" style="color: var(--color-cyan);">-</span> |
                                    Time: <span id="committee-risk-time">-</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.4rem 0 0 0;" id="committee-risk-reason">Awaiting risk parameters check.</p>
                            </div>

                            <!-- Execution Committee Card -->
                            <div class="hk-committee-card waiting" id="committee-execution">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong>Execution Committee</strong>
                                    <span class="hk-badge hk-badge-warning" id="committee-execution-status">WAITING</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.4rem;">
                                    Vote: <span id="committee-execution-vote" style="color: #fff;">-</span> |
                                    Confidence: <span id="committee-execution-confidence" style="color: var(--color-cyan);">-</span> |
                                    Time: <span id="committee-execution-time">-</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.4rem 0 0 0;" id="committee-execution-reason">Awaiting order placement.</p>
                            </div>

                            <!-- Shadow Committee Card -->
                            <div class="hk-committee-card waiting" id="committee-shadow">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <strong>Shadow Committee</strong>
                                    <span class="hk-badge hk-badge-warning" id="committee-shadow-status">WAITING</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.4rem;">
                                    Vote: <span id="committee-shadow-vote" style="color: #fff;">-</span> |
                                    Confidence: <span id="committee-shadow-confidence" style="color: var(--color-cyan);">-</span> |
                                    Time: <span id="committee-shadow-time">-</span>
                                </div>
                                <p style="font-size: 0.85rem; margin: 0.4rem 0 0 0;" id="committee-shadow-reason">Awaiting post-trade analytics.</p>
                            </div>
                        </div>
                    </div>

                    <!-- LIVE_LOGS Widget -->
                    <div id="LIVE_LOGS" class="hk-card" style="display: flex; flex-direction: column;">
                        <div class="panel-header" style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Live Shinobi Logs</h3>
                            <div style="display: flex; gap: 0.5rem;">
                                <input type="text" id="log-search" placeholder="Search..." style="background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 4px; padding: 0.2rem 0.5rem; font-size: 0.75rem; color: #fff; width: 100px;">
                                <select id="log-filter" style="background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 4px; padding: 0.2rem; font-size: 0.75rem; color: #fff;">
                                    <option value="ALL">ALL</option>
                                    <option value="INFO">INFO</option>
                                    <option value="SUCCESS">SUCCESS</option>
                                    <option value="WARNING">WARNING</option>
                                    <option value="ERROR">ERROR</option>
                                </select>
                            </div>
                        </div>
                        <div id="log-terminal" style="flex: 1; background: #000; border: 1px solid var(--border-color); border-radius: 6px; font-family: monospace; font-size: 0.8rem; padding: 0.75rem; overflow-y: auto; max-height: 400px; min-height: 250px; color: #00ff88; line-height: 1.4;">
                            <!-- Log messages stream here -->
                            <div style="color: var(--text-muted);">[SYSTEM] Shinobi Live Log Terminal initialized. Listening to EventBus...</div>
                        </div>
                    </div>
                </div>

                <!-- NO TRADE TODAY Widget / Overlay -->
                <div id="NO_TRADE_DAY" class="hk-card" style="display: none; border-color: var(--color-gold); background: rgba(18, 14, 10, 0.85); margin-bottom: 1.5rem;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
                        <div>
                            <span class="hk-badge hk-badge-warning" style="font-size: 0.9rem; padding: 0.4rem 0.8rem;">NO TRADE TODAY</span>
                            <p style="font-size: 0.95rem; margin: 0.75rem 0 0 0; color: #fff;" id="no-trade-reason-summary">
                                No trades taken today due to strict risk parameters or lack of setups.
                            </p>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; width: 100%; max-width: 600px; margin-top: 1rem;">
                            <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
                                <span style="font-size: 0.7rem; color: var(--text-muted); display: block; text-transform: uppercase;">Risk Score</span>
                                <strong id="no-trade-risk-score" style="color: var(--color-gold); font-size: 1.1rem;">-</strong>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
                                <span style="font-size: 0.7rem; color: var(--text-muted); display: block; text-transform: uppercase;">Rejected Opps</span>
                                <strong id="no-trade-rejected-count" style="color: var(--color-red); font-size: 1.1rem;">-</strong>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
                                <span style="font-size: 0.7rem; color: var(--text-muted); display: block; text-transform: uppercase;">Expected Edge</span>
                                <strong id="no-trade-expected-edge" style="color: var(--text-primary); font-size: 1.1rem;">-</strong>
                            </div>
                            <div style="background: rgba(255,255,255,0.02); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05);">
                                <span style="font-size: 0.7rem; color: var(--text-muted); display: block; text-transform: uppercase;">Capital Preservation</span>
                                <strong id="no-trade-preservation-score" style="color: var(--color-green); font-size: 1.1rem;">-</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Secondary Row (Positions, Watchlist, Market Intel) -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 1.5rem;">
                    
                    <!-- ACTIVE_POSITIONS Widget -->
                    <div id="ACTIVE_POSITIONS" class="hk-card">
                        <div class="panel-header" style="margin-bottom: 1rem;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Active Positions</h3>
                        </div>
                        <div class="table-container inline">
                            <table class="data-table-sm" id="table-ops-positions">
                                <thead>
                                    <tr>
                                        <th>Asset</th>
                                        <th>Side</th>
                                        <th>Qty</th>
                                        <th>Entry</th>
                                        <th>Current</th>
                                        <th>PnL</th>
                                    </tr>
                                </thead>
                                <tbody id="body-ops-positions">
                                    <tr>
                                        <td colspan="6" class="empty-state">No active positions.</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- OPEN_OPPORTUNITIES & WATCHLIST Widget -->
                    <div id="OPEN_OPPORTUNITIES" class="hk-card">
                        <div class="panel-header" style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Open Opportunities</h3>
                            <span id="WATCHLIST" class="hk-badge hk-badge-info" style="font-size: 0.7rem;">Watchlist: Active</span>
                        </div>
                        <div class="table-container inline">
                            <table class="data-table-sm" id="table-radar">
                                <thead>
                                    <tr>
                                        <th>Asset</th>
                                        <th>Category</th>
                                        <th>Conviction</th>
                                        <th>Risk</th>
                                        <th>Horizon</th>
                                    </tr>
                                </thead>
                                <tbody id="body-radar">
                                    <tr>
                                        <td colspan="5" class="empty-state">Loading opportunities...</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- MARKET_INTELLIGENCE & RISK_PANEL Widget -->
                    <div id="MARKET_INTELLIGENCE" class="hk-card">
                        <div class="panel-header" style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Market Intelligence & Risk</h3>
                            <span id="RISK_PANEL" class="hk-badge hk-badge-success">Risk Check: PASS</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem;">
                                <span style="color: var(--text-muted); font-size: 0.85rem;">Macro Regime:</span>
                                <strong id="ops-macro-regime" style="color: #fff; font-size: 0.85rem;">STATIONARY</strong>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem;">
                                <span style="color: var(--text-muted); font-size: 0.85rem;">Breadth Health:</span>
                                <strong id="ops-breadth" style="color: #fff; font-size: 0.85rem;">50.0%</strong>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem;">
                                <span style="color: var(--text-muted); font-size: 0.85rem;">FII/DII Flows:</span>
                                <strong id="ops-flows" style="color: #fff; font-size: 0.85rem;">NEUTRAL</strong>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span style="color: var(--text-muted); font-size: 0.85rem;">Options Sentiment:</span>
                                <strong id="ops-options" style="color: #fff; font-size: 0.85rem;">NEUTRAL</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- COMMANDER_CHAT Widget (Ask Hokage Chat) -->
                <div id="COMMANDER_CHAT" class="hk-card" style="margin-bottom: 1.5rem;">
                    <div class="panel-header" style="margin-bottom: 1rem;">
                        <h3 style="margin: 0; font-size: 1rem; color: var(--color-gold);">Ask Hokage (Conversational Command)</h3>
                    </div>
                    <div class="chat-box-inline">
                        <div class="chat-messages" id="warroom-chat-messages">
                            <div class="message system">
                                <div class="bubble">
                                    Welcome, Commander. Ask me any question. I will search across stocks, commodities, forex, and crypto.
                                </div>
                            </div>
                        </div>
                        <div class="chat-suggestions inline">
                            <span class="chip" data-query="Where is the best opportunity today?">Best Opportunity?</span>
                            <span class="chip" data-query="Why did we reject Reliance today?">Why reject Reliance?</span>
                            <span class="chip" data-query="What is our current risk level?">Current Risk?</span>
                            <span class="chip" data-query="What lessons did we learn recently?">Takeaways?</span>
                        </div>
                        <div class="chat-input-bar" style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                            <input type="text" id="warroom-input-chat" placeholder="Ask Hokage naturally..." style="flex: 1; background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); border-radius: 4px; padding: 0.5rem; color: #fff;">
                            <button id="warroom-btn-chat-send" class="btn-primary-sm" style="padding: 0.5rem 1rem;">Send</button>
                        </div>
                    </div>
                </div>
            </section>
"""

content = content[:start_idx] + new_home_html + content[end_idx:]

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated index.html successfully!")
