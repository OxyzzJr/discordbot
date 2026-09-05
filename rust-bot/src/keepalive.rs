//! Serveur HTTP keep-alive (portage de `utils/keepalive.py`).
//!
//! Flask + waitress sont remplaces par axum ; les trois routes et la forme des
//! reponses JSON sont conservees a l'identique pour Docker / Render.

use std::time::{SystemTime, UNIX_EPOCH};

use axum::{routing::get, Json, Router};
use serde_json::json;

fn epoch_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

pub fn keep_alive(start_epoch: f64) {
    tokio::spawn(async move {
        let app = Router::new()
            .route(
                "/",
                get(|| async { "Bot de modération Discord en ligne !" }),
            )
            .route(
                "/status",
                get(move || async move {
                    let now = epoch_secs();
                    Json(json!({
                        "statut": "en ligne",
                        "timestamp": now,
                        "uptime_secondes": (now - start_epoch) as i64,
                    }))
                }),
            )
            .route(
                "/health",
                get(|| async { Json(json!({ "sain": true, "service": "discord-bot" })) }),
            );

        // Port 5000 par defaut (comme `utils/keepalive.py`), surchargeable
        // par `KEEPALIVE_PORT` pour pouvoir cohabiter avec l'ancien bot.
        let port: u16 = std::env::var("KEEPALIVE_PORT")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(5000);

        match tokio::net::TcpListener::bind(("0.0.0.0", port)).await {
            Ok(listener) => {
                tracing::info!("Serveur keep-alive démarré sur le port {port}");
                if let Err(e) = axum::serve(listener, app).await {
                    tracing::error!("Erreur serveur keep-alive : {e}");
                }
            }
            Err(e) => tracing::error!("Erreur serveur keep-alive : {e}"),
        }
    });
}

pub fn now_epoch() -> f64 {
    epoch_secs()
}
