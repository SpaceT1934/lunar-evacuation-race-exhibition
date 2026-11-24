import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { HardwareSimulator } from '../../sandbox/simulator.mjs';

const exec = promisify(execFile);
const checkScript = fileURLToPath(new URL('./straight-turn.py', import.meta.url));
const legScript = fileURLToPath(new URL('./race-straight-leg.py', import.meta.url));

export class StraightMatch extends HardwareSimulator {
  constructor(send, python, onFault, runner = exec) {
    super(send);
    this.python = python;
    this.onFault = onFault;
    this.runner = runner;
    this.jobs = new Map();
    this.generation = 0;
    this.checking = false;
    this.origins = null;
  }

  get ready() {
    return this.origins !== null && !this.checking;
  }

  run(script, args, timeout, signal) {
    return this.runner(this.python, [script, ...args], {
      timeout,
      signal,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
  }

  async arm() {
    if (this.running || this.checking || this.jobs.size) throw Error('实车联调正在运行');
    this.checking = true;
    this.origins = null;
    const generation = this.generation;
    try {
      const origins = {};
      for (const side of ['blue', 'gold']) {
        const { stdout } = await this.run(checkScript, ['--rover', side, '--check'], 16000);
        const check = JSON.parse(stdout);
        if (!check.ready) throw Error(check.message || '实车未就绪');
        origins[side] = check.position_mm;
      }
      if (generation !== this.generation) throw Error('联调已取消');
      this.origins = origins;
    } finally {
      this.checking = false;
    }
  }

  activate(robot, plan, reply) {
    const previousStage = this.jobs.get(robot.id)?.stage;
    super.activate(robot, plan, reply);
    if (previousStage === robot.stage) return;
    const side = robot.id.slice('rover-'.length);
    const origin = this.origins?.[side];
    if (!origin) {
      this.onFault('实车起点未确认');
      return;
    }
    const job = { stage: robot.stage, controller: new AbortController(), done: false };
    this.jobs.set(robot.id, job);
    this.run(
      legScript,
      [side, String(job.stage), ...origin.map(String), String(plan.route.length_cm / 2)],
      100000,
      job.controller.signal,
    )
      .then(({ stdout }) => {
        if (this.jobs.get(robot.id) !== job) return;
        const result = JSON.parse(stdout);
        if (!result.stopped || result.stage !== job.stage) throw Error('未确认实车停稳');
        job.done = true;
      })
      .catch((error) => {
        if (this.jobs.get(robot.id) === job)
          this.onFault(`${side} 第 ${job.stage} 段：${error.stderr?.trim() || error.message}`);
      });
  }

  canFinishStage(robot) {
    return this.jobs.get(robot.id)?.done === true;
  }

  cancel() {
    this.generation++;
    this.origins = null;
    for (const job of this.jobs.values()) {
      if (!job.done) job.controller.abort();
    }
    this.jobs.clear();
  }
}
