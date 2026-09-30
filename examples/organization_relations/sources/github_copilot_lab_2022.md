# Research: quantifying GitHub Copilot's impact on developer productivity and happiness

> Frozen snapshot (source s1). Eirini Kalliamvakou, The GitHub Blog, 2022-09-07.
> URL: https://github.blog/news-insights/research/research-quantifying-github-copilots-impact-on-developer-productivity-and-happiness/

## Why is developer productivity so difficult to measure?

When it comes to measuring developer productivity, there is little consensus and there are far
more questions than answers.

## How do we think about developer productivity at GitHub?

After early observations and interviews with users, we surveyed more than 2,000 developers to
learn at scale about their experience using GitHub Copilot.

### Finding 1: Developer productivity goes beyond speed

- Improving developer satisfaction. Between 60–75% of users reported they feel more fulfilled
  with their job, feel less frustrated when coding, and are able to focus on more satisfying work
  when using GitHub Copilot.
- Conserving mental energy. Developers reported that GitHub Copilot helped them stay in the flow
  (73%) and preserve mental effort during repetitive tasks (87%).

### Finding 2: … but speed is important, too

In the survey, we saw that developers reported they complete tasks faster when using GitHub
Copilot, especially repetitive ones. That was an expected finding (GitHub Copilot writes faster
than a human, after all), but >90% agreement was still a pleasant surprise. Developers
overwhelmingly perceive that GitHub Copilot is helping them complete tasks faster—can we observe
and measure that effect in practice? For that we conducted a controlled experiment.

We recruited 95 professional developers, split them randomly into two groups, and timed how long
it took them to write an HTTP server in JavaScript. One group used GitHub Copilot to complete the
task, and the other one didn't. We tried to control as many factors as we could–all developers
were already familiar with JavaScript, we gave everyone the same instructions, and we leveraged
GitHub Classroom to automatically score submissions for correctness and completeness with a test
suite.

In the experiment, we measured—on average—how successful each group was in completing the task and
how long each group took to finish.

- The group that used GitHub Copilot had a higher rate of completing the task (78%, compared to
  70% in the group without Copilot).
- The striking difference was that developers who used GitHub Copilot completed the task
  significantly faster–55% faster than the developers who didn't use GitHub Copilot. Specifically,
  the developers using GitHub Copilot took on average 1 hour and 11 minutes to complete the task,
  while the developers who didn't use GitHub Copilot took on average 2 hours and 41 minutes. These
  results are statistically significant (P=.0017) and the 95% confidence interval for the
  percentage speed gain is [21%, 89%].

## What do these findings mean for developers?

In our research, we saw that GitHub Copilot supports faster completion times, conserves
developers' mental energy, helps them focus on more satisfying work, and ultimately find more fun
in the coding they do.

## Acknowledgements

GitHub Next conducted the experiment in partnership with the Microsoft Office of the Chief
Economist, and specifically in collaboration with Sida Peng and Aadharsh Kannan.
