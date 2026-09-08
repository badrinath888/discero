import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "https://finsigh.onrender.com";
const EMAIL = __ENV.E2E_USER_EMAIL;
const PASSWORD = __ENV.E2E_USER_PASSWORD;

const apiLatency = new Trend("discero_api_latency", true);
const apiErrors = new Rate("discero_api_errors");

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<2000"],
    discero_api_errors: ["rate<0.01"],
  },
};

export function setup() {
  if (!EMAIL || !PASSWORD) {
    throw new Error(
      "Set E2E_USER_EMAIL and E2E_USER_PASSWORD before running the test"
    );
  }

  const response = http.post(
    `${BASE_URL}/users/login`,
    JSON.stringify({
      email: EMAIL,
      password: PASSWORD,
    }),
    {
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  const ok = check(response, {
    "login succeeded": (r) => r.status === 200,
  });

  if (!ok) {
    throw new Error(`Login failed with status ${response.status}`);
  }

  const body = response.json();

  return {
    token: body.access_token,
    userId: body.user.id,
  };
}

function readEndpoint(url, token, name) {
  const response = http.get(url, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    tags: {
      endpoint: name,
    },
  });

  apiLatency.add(response.timings.duration);

  const ok = check(response, {
    [`${name} status 200`]: (r) => r.status === 200,
  });

  apiErrors.add(!ok);
}

export default function (data) {
  const headers = data.token;
  const userId = data.userId;

  readEndpoint(
    `${BASE_URL}/users/me`,
    headers,
    "users_me"
  );

  readEndpoint(
    `${BASE_URL}/users/${userId}/accounts`,
    headers,
    "accounts"
  );

  readEndpoint(
    `${BASE_URL}/users/${userId}/summary/overview`,
    headers,
    "overview"
  );

  readEndpoint(
    `${BASE_URL}/users/${userId}/transactions`,
    headers,
    "transactions"
  );

  sleep(1);
}
