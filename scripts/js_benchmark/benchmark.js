import { tableFromIPC } from 'apache-arrow';
import fetch from 'node-fetch';
import { performance } from 'perf_hooks';

// Usage: node benchmark.js <URL> <TOKEN> <DATASET_ID>
const args = process.argv.slice(2);
if (args.length < 3) {
    console.error("Usage: node benchmark.js <URL> <TOKEN> <DATASET_ID>");
    process.exit(1);
}

const [baseUrl, token, datasetId] = args;
const ARROW_ENDPOINT = `${baseUrl}/v1/arrow`;

async function runBenchmark() {
    console.log(`[JS Client] connecting to ${ARROW_ENDPOINT}...`);

    const body = {
        datasetId: datasetId,
        // Request 3000 variables explicitly to force check
        // We generate v1..v3000 in python script
        vars: Array.from({ length: 3000 }, (_, i) => `v${i + 1}`),
        limit: 1000,
        includeObsNo: true
    };

    const start = performance.now();

    try {
        const response = await fetch(ARROW_ENDPOINT, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify(body)
        });

        const ttfb = performance.now();
        console.log(`[JS Client] TTFB: ${(ttfb - start).toFixed(2)}ms`);

        if (!response.ok) {
            const text = await response.text();
            console.error(`[JS Client] Error ${response.status}: ${text}`);
            process.exit(1);
        }

        const buffer = await response.arrayBuffer();
        const downloadEnd = performance.now();
        console.log(`[JS Client] Download: ${(downloadEnd - ttfb).toFixed(2)}ms, Size: ${(buffer.byteLength / 1024 / 1024).toFixed(2)} MB`);

        const table = tableFromIPC(new Uint8Array(buffer));
        const parseEnd = performance.now();

        console.log(`[JS Client] Parse Arrow: ${(parseEnd - downloadEnd).toFixed(2)}ms`);
        console.log(`[JS Client] Total Time: ${(parseEnd - start).toFixed(2)}ms`);
        console.log(`[JS Client] Stats: ${table.numRows} rows, ${table.numCols} columns`);

    } catch (error) {
        console.error("[JS Client] Failed:", error);
        process.exit(1);
    }
}

runBenchmark();
